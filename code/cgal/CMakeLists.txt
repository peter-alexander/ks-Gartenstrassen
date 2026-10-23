cmake_minimum_required(VERSION 3.16)
project(ks_gartenstrassen_cgal LANGUAGES CXX)

find_package(CGAL REQUIRED COMPONENTS Core)

add_executable(cgal_voronoi_edges segment_voronoi_edges.cpp)
target_compile_features(cgal_voronoi_edges PRIVATE cxx_std_17)
target_link_libraries(cgal_voronoi_edges PRIVATE CGAL::CGAL)

add_executable(cgal_voronoi_faces segment_voronoi_faces.cpp)
target_compile_features(cgal_voronoi_faces PRIVATE cxx_std_17)
target_link_libraries(cgal_voronoi_faces PRIVATE CGAL::CGAL CGAL::CGAL_Core)

include(CTest)
if(BUILD_TESTING)
	find_package(Python3 REQUIRED COMPONENTS Interpreter)
	add_executable(cgal_voronoi_faces_failfast_test
		segment_voronoi_faces.cpp)
	target_compile_features(cgal_voronoi_faces_failfast_test PRIVATE cxx_std_17)
	target_compile_definitions(cgal_voronoi_faces_failfast_test PRIVATE
		KS_CGAL_TEST_DISABLE_EXACT_VERTEX_FALLBACK=1)
	target_link_libraries(cgal_voronoi_faces_failfast_test PRIVATE
		CGAL::CGAL CGAL::CGAL_Core)
	add_test(NAME cgal_voronoi_faces_nonfinite_regression
		COMMAND ${Python3_EXECUTABLE}
			${CMAKE_CURRENT_SOURCE_DIR}/tests/test_segment_voronoi_faces.py
			$<TARGET_FILE:cgal_voronoi_faces>
			${CMAKE_CURRENT_SOURCE_DIR}/tests/data/nonfinite_group_a.txt
			${CMAKE_CURRENT_SOURCE_DIR}/tests/data/nonfinite_group_b.txt
			$<TARGET_FILE:cgal_voronoi_faces_failfast_test>)
endif()
