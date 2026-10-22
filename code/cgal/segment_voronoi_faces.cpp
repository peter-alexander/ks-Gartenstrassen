// Native CGAL Voronoi faces with original input-segment provenance.
// Each emitted Face corresponds to an actual CGAL segment site, NOT to
// a polygon reconstructed from a global anonymous dual-edge line network.
// stdin: integer millimetre x1 y1 x2 y2 per input segment (including frame).
// output:
// F sx1 sy1 sx2 sy2   -- native supporting (inserted) CGAL segment
// P x y                 -- native point-site Face (later filtered by original-line vertex index)
// H x1 y1 x2 y2       -- ordered halfedge from its source to its target
// S x1 y1 x2 y2       -- one linearized bisector chord of that halfedge
// E                    -- end halfedge
// Z                    -- end face
// Both segment and bounded point-site faces emitted with native site provenance.
// Original LINEAR_USE ownership of point sites is resolved in Python from original vertices.
#include <CGAL/Simple_cartesian.h>
#include <CGAL/Segment_Delaunay_graph_2.h>
#include <CGAL/Segment_Delaunay_graph_filtered_traits_2.h>
#include <CGAL/Voronoi_diagram_2.h>
#include <CGAL/Segment_Delaunay_graph_adaptation_traits_2.h>
#include <CGAL/Segment_Delaunay_graph_adaptation_policies_2.h>

#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>
#include <utility>

using Kernel = CGAL::Simple_cartesian<double>;
using Traits = CGAL::Segment_Delaunay_graph_filtered_traits_2<Kernel>;
using Diagram = CGAL::Segment_Delaunay_graph_2<Traits>;
using Adaptation = CGAL::Segment_Delaunay_graph_adaptation_traits_2<Diagram>;
using Policy = CGAL::Segment_Delaunay_graph_degeneracy_removal_policy_2<Diagram>;
using Voronoi = CGAL::Voronoi_diagram_2<Diagram, Adaptation, Policy>;
using Point = Kernel::Point_2;

struct Chords {
	std::ostream& out;
	std::size_t segments=0;
	std::size_t rays=0;
	std::size_t lines=0;

	Chords& operator<<(const Kernel::Segment_2& segment) {
		const auto a=segment.source(),b=segment.target();
		out << "S " << a.x() << " " << a.y() << " "
			<< b.x() << " " << b.y() << "\n";
		++segments;
		return *this;
	}
	Chords& operator<<(const Kernel::Ray_2& ray) {
		const auto a=ray.source(),b=ray.second_point();
		out << "R " << a.x() << " " << a.y() << " "
			<< b.x() << " " << b.y() << "\n";
		++rays;
		return *this;
	}
	Chords& operator<<(const Kernel::Line_2& line) {
		const auto a=line.point(0),b=line.point(1);
		out << "L " << a.x() << " " << a.y() << " "
			<< b.x() << " " << b.y() << "\n";
		++lines;
		return *this;
	}
};

int main(int argc,char** argv) {
	std::string path;
	for (int i=1;i<argc;++i) {
		const std::string option=argv[i];
		if (option=="--faces" && i+1<argc)
			path=argv[++i];
		else {
			std::cerr << "Unknown/incomplete argument: " << option << "\n";
			return 2;
		}
	}
	if (path.empty()) {
		std::cerr << "Usage: --faces PATH\n";
		return 2;
	}
	try {
		Diagram diagram;
		std::int64_t x1,y1,x2,y2;
		std::size_t n=0;
		while (std::cin >> x1 >> y1 >> x2 >> y2) {
			if (x1==x2 && y1==y2)
				throw std::runtime_error("Degenerate input segment");
			diagram.insert(Point(double(x1),double(y1)),
				Point(double(x2),double(y2)));
			++n;
		}
		if (!std::cin.eof() || n==0)
			throw std::runtime_error("Invalid or empty input");
		if (!diagram.is_valid(false,1))
			throw std::runtime_error("Segment Delaunay graph invalid");

		Voronoi vd(std::move(diagram),true);
		std::ofstream out(path);
		if (!out)
			throw std::runtime_error("Cannot open face output");
		out << std::setprecision(17);
		Chords chords{out};
		std::size_t segment_faces=0;
		std::size_t point_faces=0;
		std::size_t unbounded_point_faces=0;
		std::size_t unbounded_segment_faces=0;
		std::size_t halfedges=0;

		for (auto face=vd.faces_begin();face!=vd.faces_end();++face) {
			const auto site=face->dual()->site();
			if (!site.is_point() && !site.is_segment())
				throw std::runtime_error("Unexpected CGAL site");
			if (face->is_unbounded()) {
				// Do not fabricate a finite polygon for an infinite Face.
				if (site.is_point())
					++unbounded_point_faces;
				else
					++unbounded_segment_faces;
				continue;
			}
			if (site.is_point()) {
				const auto p=site.point();
				out << "P " << p.x() << " " << p.y() << "\n";
			} else {
				const auto supporting=site.supporting_site();
				const auto a=supporting.source(),b=supporting.target();
				out << "F " << a.x() << " " << a.y() << " "
					<< b.x() << " " << b.y() << "\n";
			}
			auto current=vd.ccb_halfedges(face);
			auto first=current;
			do {
				if (!current->has_source() || !current->has_target())
					throw std::runtime_error(
						"Bounded Voronoi face contains infinite halfedge");
				const auto src=current->source()->point();
				const auto dst=current->target()->point();
				out << "H " << src.x() << " " << src.y() << " "
					<< dst.x() << " " << dst.y() << "\n";
				vd.dual().draw_dual_edge(current->dual(),chords);
				out << "E\n";
				++halfedges;
				++current;
			} while (current!=first);
			out << "Z\n";
			if (site.is_point())
				++point_faces;
			else
				++segment_faces;
		}
		if (!out.good())
			throw std::runtime_error("Face output write failed");
		std::cout << "{\"status\":\"ok\",\"input_segments\":" << n
			<< ",\"segment_faces\":" << segment_faces
			<< ",\"point_faces_exported\":" << point_faces
			<< ",\"unbounded_point_faces_omitted\":" << unbounded_point_faces
			<< ",\"unbounded_segment_faces_omitted\":"
			<< unbounded_segment_faces
			<< ",\"halfedges\":" << halfedges
			<< ",\"draw_segments\":" << chords.segments
			<< ",\"draw_rays\":" << chords.rays
			<< ",\"draw_lines\":" << chords.lines
			<< "}\n";
		return 0;
	} catch (const std::exception& e) {
		std::cerr << "CGAL native face export: " << e.what() << "\n";
		return 1;
	}
}
