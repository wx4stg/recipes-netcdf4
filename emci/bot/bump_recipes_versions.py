import contextlib
import subprocess
import os
from pathlib import Path
from ruamel.yaml import YAML
import pprint
import jinja2
import copy
from .next_version import next_version
from .url_exists import url_exists
from .hash_url import hash_url
from ..git_utils import bot_github_user_ctx, git_branch_ctx, make_pr_for_recipe, automerge_is_enabled
import sys
import json

# custom error derived from Exception
# to say that the recipe cannot be handled
class CannotHandleRecipeException(Exception):
    
    def __init__(self, recipe_dir, msg):
        self.recipe_dir = recipe_dir
        self.msg = msg
        super().__init__(f"Cannot handle recipe in {recipe_dir}: {msg}")


def get_new_version(recipe_file, is_ratler):
    # read the file
    with open(recipe_file) as file:
        recipe = YAML().load(file)

    # get context 
    try:
        context = recipe['context']
    except KeyError:
        raise CannotHandleRecipeException(recipe_file, "No context in recipe")


    # get version from context
    try:
        version = context['version']
    except KeyError:
        raise CannotHandleRecipeException(recipe_file, "No version in context")
            
    # get the url from the source
    try:
        source = recipe['source']
    except KeyError:
        raise CannotHandleRecipeException(recipe_file, "No source in recipe")

    if isinstance(source, list):
        if len(source) > 1:
            raise CannotHandleRecipeException(recipe_file, "Multiple sources")
        source = source[0]

    try:
        url_template = source['url']
    except KeyError:
        raise CannotHandleRecipeException(recipe_file, "No url in source")

    # make sure sha256 is in source
    if 'sha256' not in source:
        raise CannotHandleRecipeException(recipe_file, "No sha256 in source")
    
    # check that the url is a template
    if is_ratler:
        if "${{" not in url_template or "}}" not in url_template:
            raise CannotHandleRecipeException(recipe_file, "url is not a template")
    else:
        if "{{" not in url_template or "}}" not in url_template:
            raise CannotHandleRecipeException(recipe_file, "url is not a template")
    
    if is_ratler:
        environment = jinja2.Environment(trim_blocks=True,variable_start_string='${{', variable_end_string='}}')
    else:
        environment = jinja2.Environment(trim_blocks=True,variable_start_string='{{', variable_end_string='}}')

    # get name from dir
    name = recipe_file.parent.name

    print(f"{name} current version: ", version)
    for new_version in next_version(version):
        # render the new url with the new version
        new_version_context = copy.deepcopy(context)
        new_version_context['version'] = new_version
        new_url = environment.from_string(url_template).render(**new_version_context)
        if url_exists(new_url):
            print(f"- found new version: {version}")

            # hash the new url
            new_sha256 = hash_url(new_url, hash_type='sha256')
            print(f"- new sha256: {new_sha256}")

            return version, new_version, new_sha256
    
    return None, None,None


def update_recipe_version(recipe_file, new_version, new_sha256, is_ratler):

    # read the file
    with open(recipe_file) as file:
        recipe = YAML().load(file)

    # get context
    context = recipe['context']
    context['version'] = new_version

    # update sha256 in source
    source = recipe['source']
    if isinstance(source, list):
        if len(source) > 1:
            raise CannotHandleRecipeException(recipe_file, "Multiple sources")
        source = source[0]
    source['sha256'] = new_sha256

    # write the file
    with open(recipe_file, 'w') as file:
        YAML().dump(recipe, file)

def make_pr_title(name, old_version, new_version):
    return f"Update {name} from {old_version} to {new_version} -- TESTPR"

def bump_recipe_version(recipe_dir):

    recipe_locations = [("recipe.yaml", False), ("rattler_recipe.yaml", True)]

    current_version = None
    new_version = None
    new_sha256 = None
    for  recipe_fname, is_rattler in  recipe_locations:
        if (recipe_dir / recipe_fname).exists():
            recipe_file = recipe_dir / recipe_fname
            cv, nv, h = get_new_version(recipe_file, is_ratler=is_rattler)
            if nv is not None:
                new_version = nv
                current_version = cv
                new_sha256 = h
                break

    # no new version found -- nothing to do
    if new_version is None:
        return False, None, None
    
    # use the last directory in the path as the branch name
    name = recipe_dir.name

    # check if the recipe has test_.py files
    # if it does, we can mark the PR as automerge
    test_files = [f for f in recipe_dir.iterdir() if f.name.startswith("test_") and f.name.endswith(".py")]
    automerge = len(test_files) > 0


    branch_name = f"bump-{name}_{current_version}_to_{new_version}"


    with git_branch_ctx(branch_name):

        # update the recipe
        for recipe_fname, is_rattler in recipe_locations:
            if (recipe_dir / recipe_fname).exists():
                recipe_file = recipe_dir / recipe_fname
                update_recipe_version(recipe_file, new_version=new_version, new_sha256=new_sha256, is_ratler=is_rattler)
        
        # commit the changes and make a PR
        pr_title = make_pr_title(name, current_version, new_version)
        print(f"Making PR for {name} with title: {pr_title}")
        make_pr_for_recipe(recipe_dir=recipe_dir, pr_title=pr_title, branch_name=branch_name, automerge=automerge)
            
    return True , current_version, new_version

           
def try_to_merge_pr(pr):

    passed = subprocess.run(
        ['gh', 'pr', 'checks', str(pr)],
        stdout=subprocess.DEVNULL,
    )

    # Debug: print labels
    labels = json.loads(subprocess.check_output(['gh', 'pr', 'view', str(pr), '--json', 'labels']).decode('utf-8'))
    print(f'Labels for PR {pr}: {labels}')

    if passed.returncode == 0 and automerge_is_enabled(pr):
        # PR passed and automerge is enabled, let's merge it
        subprocess.check_output(['gh', 'pr', 'comment', str(pr), '--body', 'CI passed! I\'m merging'])
        subprocess.check_output(['gh', 'pr', 'merge', str(pr), '--rebase', '--delete-branch', '--admin'])
    else:
        # Pin recipe maintainer? Or add assignee?
        subprocess.check_output(['gh', 'pr', 'edit', str(pr), '--add-label', 'Needs Human Review'])

        message = 'Either the CI is failing, or the recipe is not tested. I need help from a human.'

        try:
            # Running edit-last in case there was already a comment, we don't want to spam with comments
            subprocess.check_output(['gh', 'pr', 'comment', str(pr), '--body', message, '--edit-last'])
        except:
            subprocess.check_output(['gh', 'pr', 'comment', str(pr), '--body', message])


def bump_recipe_versions(recipe_dir, use_bot=True, pr_limit=5):

    # get all opened PRs
    with bot_github_user_ctx(bypass=not use_bot):

        # Check for opened PRs and merge them if the CI passed
        print("Checking opened PRs and merge them if green!")
        prs = subprocess.check_output(
            ['gh', 'pr', 'list', '--author', 'emscripten-forge-bot'],
        ).decode('utf-8').split('\n')

        prs_id = [line.split()[0] for line in prs if line]
        prs_packages = [line.split()[2] for line in prs if line]

        # Merge PRs if possible
        for pr in prs_id:
            try_to_merge_pr(pr)

        
        all_recipes = [recipe for recipe in Path(recipe_dir).iterdir() if recipe.is_dir()]
  

        # only recipes for which there is no opened PR
        all_recipes = [recipe for recipe in all_recipes if recipe.name not in prs_packages]
        
        skip_recipes = [
            'python', 'python_abi', 'libpython',
            'sqlite', 'robotics-toolbox-python', 'xvega', 'xvega-bindings'
        ]
        all_recipes = [recipe for recipe in all_recipes if recipe.name not in skip_recipes]

        
        total_bumped = 0
        for recipe in all_recipes:
            try:
                bumped_version, old_version, new_version = bump_recipe_version(recipe)
                if bumped_version:
                    print(f"Bumped {recipe} from {old_version} to {new_version}")
                total_bumped += int(bumped_version)
            except Exception as e:
                print(f"Error in {recipe}: {e}")
            
            if pr_limit is not None and total_bumped >= pr_limit:
                break
            
        # some unstaged
        print("Total bumped: ", total_bumped)

