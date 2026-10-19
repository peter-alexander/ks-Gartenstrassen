// CGAL segment-site Voronoi boundary export for debug polygonization.
// stdin: x1 y1 x2 y2 in integer millimetres, one site per row.
// --bounds xmin ymin xmax ymax: clip candidate output to this integer-mm window.
// --edges PATH: write S (segment), R (ray), L (line) records.
// Parabolic boundaries are linearized by CGAL's Parabola_segment_2::draw.
// Never treat this approximation as a verified exact polygon partition.
#include <CGAL/Simple_cartesian.h>
#include <CGAL/Segment_Delaunay_graph_2.h>
#include <CGAL/Segment_Delaunay_graph_filtered_traits_2.h>

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>

using Kernel = CGAL::Simple_cartesian<double>;
using Traits = CGAL::Segment_Delaunay_graph_filtered_traits_2<Kernel>;
using Diagram = CGAL::Segment_Delaunay_graph_2<Traits>;
using Point = Kernel::Point_2;

struct Recorder {
	std::ostream& output;
	double xmin, ymin, xmax, ymax;
	std::size_t segments = 0, rays = 0, lines = 0;

	bool may_intersect(const Point& a, const Point& b) const {
		return !(std::max(a.x(),b.x()) < xmin ||
			std::min(a.x(),b.x()) > xmax ||
			std::max(a.y(),b.y()) < ymin ||
			std::min(a.y(),b.y()) > ymax);
	}
	Recorder& operator<<(const Kernel::Segment_2& segment) {
		const auto a=segment.source(), b=segment.target();
		if (may_intersect(a,b)) {
			output << "S " << a.x() << " " << a.y() << " "
				<< b.x() << " " << b.y() << "\n";
			++segments;
		}
		return *this;
	}
	Recorder& operator<<(const Kernel::Ray_2& ray) {
		const auto a=ray.source(), b=ray.second_point();
		output << "R " << a.x() << " " << a.y() << " "
			<< b.x() << " " << b.y() << "\n";
		++rays;
		return *this;
	}
	Recorder& operator<<(const Kernel::Line_2& line) {
		const auto a=line.point(0), b=line.point(1);
		output << "L " << a.x() << " " << a.y() << " "
			<< b.x() << " " << b.y() << "\n";
		++lines;
		return *this;
	}
};

int main(int argc,char** argv) {
	std::string path;
	double xmin=0,ymin=0,xmax=0,ymax=0;
	bool has_bounds=false;
	for (int i=1;i<argc;++i) {
		const std::string option=argv[i];
		if (option=="--edges" && i+1<argc) {
			path=argv[++i];
		} else if (option=="--bounds" && i+4<argc) {
			xmin=std::stod(argv[++i]);
			ymin=std::stod(argv[++i]);
			xmax=std::stod(argv[++i]);
			ymax=std::stod(argv[++i]);
			has_bounds=true;
		} else {
			std::cerr << "Unknown/incomplete argument: " << option << "\n";
			return 2;
		}
	}
	if (path.empty() || !has_bounds || !(xmin<xmax && ymin<ymax)) {
		std::cerr << "Usage: --edges FILE --bounds XMIN YMIN XMAX YMAX (mm)\n";
		return 2;
	}
	try {
		Diagram diagram;
		std::int64_t x1,y1,x2,y2;
		std::size_t n=0;
		while (std::cin >> x1 >> y1 >> x2 >> y2) {
			if (x1==x2 && y1==y2) {
				throw std::runtime_error("Degenerate input site");
			}
			diagram.insert(Point(double(x1),double(y1)),
				Point(double(x2),double(y2)));
			++n;
		}
		if (!std::cin.eof() || n==0) {
			throw std::runtime_error("Invalid or empty site stream");
		}
		if (!diagram.is_valid(false,1)) {
			throw std::runtime_error("CGAL segment Delaunay graph invalid");
		}
		std::ofstream out(path);
		if (!out) {
			throw std::runtime_error("Cannot create edge output");
		}
		out << std::setprecision(17);
		Recorder recorder{out,xmin,ymin,xmax,ymax};
		diagram.draw_dual(recorder);
		if (!out.good()) {
			throw std::runtime_error("Edge output write failed");
		}
		std::cout << "{\"status\":\"ok\",\"input_segments\":" << n
			<< ",\"segments\":" << recorder.segments
			<< ",\"rays\":" << recorder.rays
			<< ",\"lines\":" << recorder.lines << "}" << std::endl;
		return 0;
	} catch (const std::exception& e) {
		std::cerr << "CGAL Voronoi export: " << e.what() << "\n";
		return 1;
	}
}
