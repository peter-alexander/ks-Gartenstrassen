cmake_minimum_required(VERSION 3.16)
project(ks_gartenstrassen_cgal LANGUAGES CXX)

find_package(CGAL REQUIRED)

add_executable(cgal_voronoi_edges segment_voronoi_edges.cpp)
target_compile_features(cgal_voronoi_edges PRIVATE cxx_std_17)
target_link_libraries(cgal_voronoi_edges PRIVATE CGAL::CGAL)
