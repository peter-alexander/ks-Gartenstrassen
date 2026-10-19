// Isolated segment-Delaunay benchmark; diagnostic only, no production output.
// Input (stdin): one line per noded integer-millimetre segment: x1 y1 x2 y2
#include <CGAL/Simple_cartesian.h>
#include <CGAL/Segment_Delaunay_graph_2.h>
#include <CGAL/Segment_Delaunay_graph_filtered_traits_2.h>

#include <chrono>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <vector>
#include <utility>

using Kernel = CGAL::Simple_cartesian<double>;
using Traits = CGAL::Segment_Delaunay_graph_filtered_traits_2<Kernel>;
using Diagram = CGAL::Segment_Delaunay_graph_2<Traits>;
using Point = Kernel::Point_2;
using Segment = std::pair<Point, Point>;
using Clock = std::chrono::steady_clock;

int main(int argc, char** argv) {
	bool check = false;
	for (int i = 1; i < argc; ++i) {
		if (std::string(argv[i]) == "--validate") {
			check = true;
		} else {
			std::cerr << "Unknown argument: " << argv[i] << '\n';
			return 2;
		}
	}
	std::vector<Segment> segments;
	std::int64_t x1, y1, x2, y2;
	while (std::cin >> x1 >> y1 >> x2 >> y2) {
		if (x1 == x2 && y1 == y2) {
			std::cerr << "Degenerate input segment\n";
			return 2;
		}
		segments.emplace_back(Point(static_cast<double>(x1), static_cast<double>(y1)),
			Point(static_cast<double>(x2), static_cast<double>(y2)));
	}
	if (!std::cin.eof()) {
		std::cerr << "Malformed segment input\n";
		return 2;
	}
	if (segments.empty()) {
		std::cerr << "No segments provided\n";
		return 2;
	}
	try {
		Diagram diagram;
		auto begin = Clock::now();
		for (const auto& segment : segments) {
			diagram.insert(segment.first, segment.second);
		}
		auto end = Clock::now();
		const double seconds = std::chrono::duration<double>(end - begin).count();
		const bool valid = !check || diagram.is_valid(false, 1);
		std::cout << "{\"status\":\"" << (valid ? "ok" : "invalid")
			<< "\",\"segments\":" << segments.size()
			<< ",\"input_sites\":" << diagram.number_of_input_sites()
			<< ",\"output_sites\":" << diagram.number_of_output_sites()
			<< ",\"vertices\":" << diagram.number_of_vertices()
			<< ",\"faces\":" << diagram.number_of_faces()
			<< ",\"construct_s\":" << seconds
			<< ",\"validity_checked\":" << (check ? "true" : "false")
			<< "}" << std::endl;
		return valid ? 0 : 1;
	} catch (const std::exception& e) {
		std::cerr << "CGAL exception: " << e.what() << '\n';
		return 1;
	}
}
