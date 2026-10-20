// CGAL segment-site Voronoi boundary export for debug polygonization.
// stdin: x1 y1 x2 y2 in integer millimetres, one site per row.
// --bounds xmin ymin xmax ymax: clip candidate output to this integer-mm window.
// --edges PATH: write S (segment), R (ray), L (line) records.
// --sites PATH: export CGAL graph sites (point and segment generators).
// --labelled-edges PATH: E records with both generating sites, followed by
// the corresponding S/R/L dual primitives (including parabola fragments).
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

template <typename Site>
void write_site(std::ostream& out,const Site& site) {
	if (site.is_point()) {
		const auto p=site.point();
		out << "P " << p.x() << " " << p.y();
	} else if (site.is_segment()) {
		const auto a=site.source(),b=site.target();
		out << "S " << a.x() << " " << a.y() << " "
			<< b.x() << " " << b.y();
	} else {
		throw std::runtime_error("Unknown generating site");
	}
}


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
	std::string path,site_path,labelled_path,topology_path,skeleton_path,skeleton_edge_ids_path,face_incidence_path;
	double xmin=0,ymin=0,xmax=0,ymax=0;
	bool has_bounds=false;
	for (int i=1;i<argc;++i) {
		const std::string option=argv[i];
		if (option=="--face-incidence" && i+1<argc) {
			face_incidence_path=argv[++i];
		} else if (option=="--skeleton-edge-ids" && i+1<argc) {
			skeleton_edge_ids_path=argv[++i];
		} else if (option=="--edges" && i+1<argc) {
			path=argv[++i];
		} else if (option=="--sites" && i+1<argc) {
			site_path=argv[++i];
		} else if (option=="--labelled-edges" && i+1<argc) {
			labelled_path=argv[++i];
		} else if (option=="--skeleton" && i+1<argc) {
			skeleton_path=argv[++i];
		} else if (option=="--edge-topology" && i+1<argc) {
			topology_path=argv[++i];
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
		std::cerr << "Usage: --edges FILE [--sites FILE] [--labelled-edges FILE] --bounds XMIN YMIN XMAX YMAX (mm)\n";
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
		// A graph vertex stores the actual CGAL generating site, unlike
		// draw_dual() which exports only anonymous boundaries. This is an
		// independent diagnostic dataset; polygon ownership needs a
		// subsequent explicit face-to-site association.
		std::size_t point_sites=0,segment_sites=0;
		if (!site_path.empty()) {
			std::ofstream sites(site_path);
			if (!sites) throw std::runtime_error("Cannot create sites output");
			sites << std::setprecision(17);
			for (auto vertex=diagram.finite_vertices_begin();
					vertex!=diagram.finite_vertices_end();++vertex) {
				const auto site=vertex->site();
				if (site.is_point()) {
					const auto p=site.point();
					sites << "P " << p.x() << " " << p.y() << "\n";
					++point_sites;
				} else if (site.is_segment()) {
					const auto a=site.source(), b=site.target();
					sites << "S " << a.x() << " " << a.y() << " "
						<< b.x() << " " << b.y() << "\n";
					++segment_sites;
				} else {
					throw std::runtime_error("Unknown graph site type");
				}
			}
			if (!sites.good()) throw std::runtime_error("Sites output write failed");
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
		if (!skeleton_path.empty()) {
			std::ofstream skeleton(skeleton_path);
			if (!skeleton) throw std::runtime_error("Cannot create skeleton output");
			skeleton << std::setprecision(17);
			Recorder skeleton_recorder{skeleton,xmin,ymin,xmax,ymax};
			diagram.draw_skeleton(skeleton_recorder);
			if (!skeleton.good()) throw std::runtime_error("Skeleton output write failed");
		}
		std::size_t labelled_edges=0;
		std::size_t endpoint_duals=0;
		std::ofstream skeleton_edge_ids;
		if (!skeleton_edge_ids_path.empty()) {
			skeleton_edge_ids.open(skeleton_edge_ids_path);
			if (!skeleton_edge_ids) throw std::runtime_error("Cannot create skeleton edge IDs");
		}
		if (!labelled_path.empty()) {
			std::ofstream labelled(labelled_path);
			if (!labelled) throw std::runtime_error("Cannot create labelled output");
			labelled << std::setprecision(17);
			Recorder labelled_recorder{labelled,xmin,ymin,xmax,ymax};
			std::ofstream incidence;
			if (!face_incidence_path.empty()) {
				incidence.open(face_incidence_path);
				if (!incidence) throw std::runtime_error("Cannot create face incidence output");
				incidence << std::setprecision(17);
			}
			std::ofstream topology;
			if (!topology_path.empty()) {
				topology.open(topology_path);
				if (!topology) throw std::runtime_error("Cannot create topology output");
				topology << std::setprecision(17);
			}
			for (auto edge=diagram.finite_edges_begin();
					edge!=diagram.finite_edges_end();++edge) {
				const auto face=edge->first;
				const int i=edge->second;
				const auto a=face->vertex(diagram.cw(i))->site();
				const auto b=face->vertex(diagram.ccw(i))->site();
				const auto endpoint_of=[](const auto& point,const auto& segment) {
					return point.is_point() && segment.is_segment() &&
						(point.point()==segment.source() || point.point()==segment.target());
				};
				const bool endpoint_pair=endpoint_of(a,b) || endpoint_of(b,a);
				if (incidence.is_open()) {
					// Face and neighbor are primal Delaunay triangular faces.
					// Their opposite sites are distinct from the two edge sites;
					// they are not asserted to be left/right Voronoi owners.
					incidence << "F " << labelled_edges << " "
						<< (diagram.is_infinite(face)?0:1) << " "
						<< (diagram.is_infinite(face->neighbor(i))?0:1)
						<< " OPP ";
					if (diagram.is_infinite(face)) incidence << "INF";
					else write_site(incidence,face->vertex(i)->site());
					incidence << " | NEIGH ";
					const auto neighbor=face->neighbor(i);
					if (diagram.is_infinite(neighbor)) incidence << "INF";
					else {
						const int mirror=neighbor->index(face);
						write_site(incidence,neighbor->vertex(mirror)->site());
					}
					incidence << "\n";
				}
				if (skeleton_edge_ids.is_open()) {
					skeleton_edge_ids << "K " << labelled_edges << " " << (endpoint_pair?0:1) << "\n";
				}
				if (endpoint_pair) ++endpoint_duals;
				if (topology.is_open()) {
					topology << "T " << labelled_edges << " " << (endpoint_pair?1:0)
						<< " CW ";
					write_site(topology,a);
					topology << " | CCW ";
					write_site(topology,b);
					topology << "\n";
				}
				labelled << "E " << labelled_edges << " ";
				write_site(labelled,a);
				labelled << " | ";
				write_site(labelled,b);
				labelled << "\n";
				diagram.draw_dual_edge(*edge,labelled_recorder);
				++labelled_edges;
			}
			if (skeleton_edge_ids.is_open() && !skeleton_edge_ids.good()) {
				throw std::runtime_error("Skeleton edge IDs write failed");
			}
			if (incidence.is_open() && !incidence.good()) {
				throw std::runtime_error("Face incidence output write failed");
			}
			if (topology.is_open() && !topology.good()) {
				throw std::runtime_error("Topology output write failed");
			}
			if (!labelled.good()) {
				throw std::runtime_error("Labelled edge output write failed");
			}
			// Exact same primitive counts are expected in both exports.
			if (labelled_recorder.segments!=recorder.segments ||
					labelled_recorder.rays!=recorder.rays ||
					labelled_recorder.lines!=recorder.lines) {
				throw std::runtime_error("Labelled/unlabelled dual mismatch");
			}
		}

		std::cout << "{\"status\":\"ok\",\"input_segments\":" << n
			<< ",\"segments\":" << recorder.segments
			<< ",\"rays\":" << recorder.rays
			<< ",\"lines\":" << recorder.lines
			<< ",\"labelled_edges\":" << labelled_edges
			<< ",\"endpoint_duals\":" << endpoint_duals
			<< ",\"point_sites\":" << point_sites
			<< ",\"segment_sites\":" << segment_sites
			<< "}" << std::endl;
		return 0;
	} catch (const std::exception& e) {
		std::cerr << "CGAL Voronoi export: " << e.what() << "\n";
		return 1;
	}
}
