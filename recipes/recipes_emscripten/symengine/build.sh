emcmake cmake \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_TESTS=OFF \
    -DBUILD_BENCHMARKS=OFF \
    -DINTEGER_CLASS=boostmp \
    -DWITH_BOOST=ON \
    -DCMAKE_PREFIX_PATH=$PREFIX \
    -DCMAKE_INSTALL_PREFIX=$PREFIX \
    -DCMAKE_INSTALL_LIBDIR=lib \
    -DBUILD_FOR_DISTRIBUTION=yes \
    -DBUILD_SHARED_LIBS=no \
    -DBoost_INCLUDE_DIR=$BUILD_PREFIX/include \
    -DWITH_SYMENGINE_THREAD_SAFE=ON \
    -DWITH_SYMENGINE_RCP=ON \
    -DWITH_FLINT=OFF \
    -DWITH_PIRANHA=OFF \
    -DWITH_GMP=OFF \
    -DWITH_MPFR=OFF \
    -DWITH_MPC=OFF \
    -DWITH_OPENMP=OFF \
    -S . \
    -B build

emmake cmake --build build --target install