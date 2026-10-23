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
#include <CGAL/Exact_predicates_exact_constructions_kernel_with_sqrt.h>
#include <CGAL/Segment_Delaunay_graph_2.h>
#include <CGAL/Segment_Delaunay_graph_filtered_traits_2.h>
#include <CGAL/Segment_Delaunay_graph_traits_2.h>
#include <CGAL/Voronoi_diagram_2.h>
#include <CGAL/Segment_Delaunay_graph_adaptation_traits_2.h>
#include <CGAL/Segment_Delaunay_graph_adaptation_policies_2.h>

#include <cmath>
#include <cstdio>
#include <cstdint>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>

using Kernel = CGAL::Simple_cartesian<double>;
using Filtered_traits = CGAL::Segment_Delaunay_graph_filtered_traits_2<Kernel>;
using Exact_sqrt_kernel =
	CGAL::Exact_predicates_exact_constructions_kernel_with_sqrt;
using Exact_sqrt_traits =
	CGAL::Segment_Delaunay_graph_traits_2<Exact_sqrt_kernel>;

namespace {

std::size_t exact_vertex_fallbacks=0;

struct Core_filter_guard {
	const bool previous=CORE::setFpFilterFlag(false);
	~Core_filter_guard() {
		CORE::setFpFilterFlag(previous);
	}
};

template<class Site>
std::string describe_site(const Site& site) {
	std::ostringstream text;
	text << std::setprecision(17);
	if (site.is_point()) {
		const auto point=site.point();
		text << "point(" << point.x() << " " << point.y() << ")";
	} else if (site.is_segment()) {
		const auto supporting=site.supporting_site();
		text << "segment(" << supporting.source().x() << " "
			<< supporting.source().y() << " -> "
			<< supporting.target().x() << " "
			<< supporting.target().y() << ")";
	} else {
		text << "unknown-site";
	}
	return text.str();
}

// CGAL's filtered construction first tries interval arithmetic. For two
// almost collinear segments with a shared endpoint and a nearby point site,
// CGAL 5.6 can return NaN instead of raising Uncertain_conversion_exception;
// the standard filter therefore never reaches its exact rational fallback.
// Retry only that failed construction with an algebraic exact kernel capable
// of square roots. Predicates, graph topology and all regular constructions
// remain on the established filtered-double traits.
struct Traits : Filtered_traits {
	using Construction_traits = Filtered_traits::Construction_traits;
	using Construction_kernel = Filtered_traits::Construction_kernel;
	using Site_2 = Filtered_traits::Site_2;
	using Point_2 = Filtered_traits::Point_2;

	struct Construct_svd_vertex_2 {
		using result_type = Point_2;

		Point_2 operator()(const Site_2& a,const Site_2& b,
				const Site_2& c) const {
			Filtered_traits::Construct_svd_vertex_2 filtered;
			const auto approximate=filtered(a,b,c);
			if (std::isfinite(approximate.x()) &&
					std::isfinite(approximate.y()))
				return approximate;
#ifdef KS_CGAL_TEST_DISABLE_EXACT_VERTEX_FALLBACK
			return approximate;
#endif

			using CK = typename Construction_traits::Kernel;
			using EK = typename Exact_sqrt_traits::Kernel;
			using C2E_base = CGAL::Cartesian_converter<
				Construction_kernel,Exact_sqrt_kernel>;
			using C2E = CGAL::SegmentDelaunayGraph_2::Cartesian_converter<
				CK,EK,C2E_base>;
			using E2C_base = CGAL::Cartesian_converter<
				Exact_sqrt_kernel,Construction_kernel,
				CGAL::To_double<typename Exact_sqrt_kernel::RT>>;
			using E2C = CGAL::SegmentDelaunayGraph_2::Cartesian_converter<
				EK,CK,E2C_base>;

			// CORE's floating filter warns to a cwd-relative Core_Diagnostics
			// file for the same near-zero radicand. Disable that secondary
			// approximation while evaluating the rare exact fallback.
			const Core_filter_guard core_filter;
			const auto exact=typename Exact_sqrt_traits::Construct_svd_vertex_2()(
				C2E()(a),C2E()(b),C2E()(c));
			const auto recovered=E2C()(exact);
			if (!std::isfinite(recovered.x()) ||
					!std::isfinite(recovered.y())) {
				throw std::runtime_error(
					"Voronoi vertex remained non-finite after algebraic exact "
					"fallback; sites: "+describe_site(a)+", "+
					describe_site(b)+", "+describe_site(c));
			}
			++exact_vertex_fallbacks;
			return recovered;
		}
	};

	Construct_svd_vertex_2 construct_svd_vertex_2_object() const {
		return Construct_svd_vertex_2();
	}
};

struct Export_context {
	std::size_t face=0;
	std::size_t halfedge=0;
	std::string generator;
};

template<class Point>
void require_finite(const Point& point,const Export_context& context,
		const std::string& calculation) {
	if (std::isfinite(CGAL::to_double(point.x())) &&
			std::isfinite(CGAL::to_double(point.y())))
		return;
	throw std::runtime_error("Face "+std::to_string(context.face)+
		", generator "+context.generator+", halfedge "+
		std::to_string(context.halfedge)+": non-finite coordinate in "+
		calculation);
}

} // namespace

using Diagram = CGAL::Segment_Delaunay_graph_2<Traits>;
using Adaptation = CGAL::Segment_Delaunay_graph_adaptation_traits_2<Diagram>;
using Policy = CGAL::Segment_Delaunay_graph_degeneracy_removal_policy_2<Diagram>;
using Voronoi = CGAL::Voronoi_diagram_2<Diagram, Adaptation, Policy>;
using Point = Kernel::Point_2;

struct Chords {
	std::ostream& out;
	const Export_context& context;
	std::size_t segments=0;
	std::size_t rays=0;
	std::size_t lines=0;

	Chords& operator<<(const Kernel::Segment_2& segment) {
		const auto a=segment.source(),b=segment.target();
		require_finite(a,context,"linearized dual segment source");
		require_finite(b,context,"linearized dual segment target");
		out << "S " << a.x() << " " << a.y() << " "
			<< b.x() << " " << b.y() << "\n";
		++segments;
		return *this;
	}
	Chords& operator<<(const Kernel::Ray_2& ray) {
		const auto a=ray.source(),b=ray.second_point();
		require_finite(a,context,"dual ray source");
		require_finite(b,context,"dual ray second point");
		out << "R " << a.x() << " " << a.y() << " "
			<< b.x() << " " << b.y() << "\n";
		++rays;
		return *this;
	}
	Chords& operator<<(const Kernel::Line_2& line) {
		const auto a=line.point(0),b=line.point(1);
		require_finite(a,context,"dual line point 0");
		require_finite(b,context,"dual line point 1");
		out << "L " << a.x() << " " << a.y() << " "
			<< b.x() << " " << b.y() << "\n";
		++lines;
		return *this;
	}
};

int main(int argc,char** argv) {
	std::string path;
	bool output_opened=false;
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
		output_opened=true;
		out << std::setprecision(17);
		Export_context context;
		Chords chords{out,context};
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
			++context.face;
			context.halfedge=0;
			context.generator=describe_site(site);
			if (site.is_point()) {
				const auto p=site.point();
				require_finite(p,context,"point generator");
				out << "P " << p.x() << " " << p.y() << "\n";
			} else {
				const auto supporting=site.supporting_site();
				const auto a=supporting.source(),b=supporting.target();
				require_finite(a,context,"segment generator source");
				require_finite(b,context,"segment generator target");
				out << "F " << a.x() << " " << a.y() << " "
					<< b.x() << " " << b.y() << "\n";
			}
			auto current=vd.ccb_halfedges(face);
			auto first=current;
			do {
				++context.halfedge;
				if (!current->has_source() || !current->has_target())
					throw std::runtime_error(
						"Bounded Voronoi face contains infinite halfedge");
				const auto src=current->source()->point();
				const auto dst=current->target()->point();
				require_finite(src,context,"native halfedge source");
				require_finite(dst,context,"native halfedge target");
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
			<< ",\"exact_vertex_fallbacks\":" << exact_vertex_fallbacks
			<< "}\n";
		return 0;
	} catch (const std::exception& e) {
		if (output_opened && std::remove(path.c_str())!=0)
			std::cerr << "CGAL native face export: failed to remove incomplete "
				"output " << path << "\n";
		std::cerr << "CGAL native face export: " << e.what() << "\n";
		return 1;
	}
}
