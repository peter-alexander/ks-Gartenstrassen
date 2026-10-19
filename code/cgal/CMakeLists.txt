cmake_minimum_required(VERSION 3.16)
project(ks_gartenstrassen_cgal LANGUAGES CXX)

find_package(CGAL REQUIRED)

add_executable(cgal_segment_benchmark segment_benchmark.cpp)
target_compile_features(cgal_segment_benchmark PRIVATE cxx_std_17)
target_link_libraries(cgal_segment_benchmark PRIVATE CGAL::CGAL)
