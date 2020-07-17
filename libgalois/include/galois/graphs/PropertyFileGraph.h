#ifndef GALOIS_LIBGALOIS_GALOIS_GRAPHS_PROPERTY_FILE_GRAPH_H_
#define GALOIS_LIBGALOIS_GALOIS_GRAPHS_PROPERTY_FILE_GRAPH_H_

#include <arrow/api.h>

#include <string>
#include <utility>
#include <vector>

#include "tsuba/RDG.h"

namespace galois::graphs {

/// A graph topology represents the adjacency information for a graph in CSR
/// format.
struct GraphTopology {
  std::shared_ptr<arrow::UInt64Array> out_indices;
  std::shared_ptr<arrow::UInt32Array> out_dests;

  uint64_t num_nodes() const { return out_indices ? out_indices->length() : 0; }

  uint64_t num_edges() const { return out_dests ? out_dests->length() : 0; }
};

/// A property graph is a graph that has properties associated with its nodes
/// and edges. A property has a name and value. Its value may be a primitive
/// type, a list of values or a composition of properties.
///
/// A PropertyFileGraph is a representation of a property graph that is backed
/// by persistent storage, and it may be a subgraph of a larger, global property
/// graph. Another way to view a PropertyFileGraph is as a container for node
/// and edge properties that can be serialized.
///
/// The main way to load and store a property graph is via an RDG. An RDG
/// manages the serialization of the various partitions and properties that
/// comprise the physical representation of the logical property graph.
class PropertyFileGraph {
  PropertyFileGraph(std::unique_ptr<tsuba::RDGFile> rdg_file, tsuba::RDG&& rdg);

  // sanity check the graph after loading
  Result<void> Validate();

  Result<void> DoWrite(tsuba::RDGHandle handle);

  tsuba::RDG rdg_;
  std::unique_ptr<tsuba::RDGFile> file_;

  // The topology is either backed by rdg_ or shared with the
  // caller of SetTopology.
  GraphTopology topology_;

public:
  /// PropertyView provides a uniform interface when you don't need to
  /// distinguish operating on edge or node properties
  struct PropertyView {
    PropertyFileGraph* g;

    std::shared_ptr<arrow::Schema> (PropertyFileGraph::*schema_fn)() const;
    std::shared_ptr<arrow::ChunkedArray> (PropertyFileGraph::*property_fn)(
        int i) const;
    std::vector<std::shared_ptr<arrow::ChunkedArray>> (
        PropertyFileGraph::*properties_fn)() const;
    Result<void> (PropertyFileGraph::*add_properties_fn)(
        const std::shared_ptr<arrow::Table>& table);
    Result<void> (PropertyFileGraph::*remove_property_fn)(int i);

    std::shared_ptr<arrow::Schema> schema() const { return (g->*schema_fn)(); }

    std::shared_ptr<arrow::ChunkedArray> Property(int i) const {
      return (g->*property_fn)(i);
    }

    std::vector<std::shared_ptr<arrow::ChunkedArray>> Properties() const {
      return (g->*properties_fn)();
    }

    Result<void>
    AddProperties(const std::shared_ptr<arrow::Table>& table) const {
      return (g->*add_properties_fn)(table);
    }

    Result<void> RemoveProperty(int i) const {
      return (g->*remove_property_fn)(i);
    }
  };

  PropertyFileGraph();

  /// Make a property graph from a constructed RDG. Take ownership of the RDG
  /// and its underlying resources.
  static Result<std::unique_ptr<PropertyFileGraph>>
  Make(std::unique_ptr<tsuba::RDGFile> rdg_file, tsuba::RDG&& rdg);

  /// Make a property graph from an RDG name.
  static Result<std::unique_ptr<PropertyFileGraph>>
  Make(const std::string& rdg_name);

  /// Make a property graph from an RDG but only load the named node and edge
  /// properties.
  ///
  /// The order of properties in the resulting graph will match the order of
  /// given in the property arguments.
  ///
  /// \returns invalid_argument if any property is not found or if there
  /// are multiple properties with the same name
  static Result<std::unique_ptr<PropertyFileGraph>>
  Make(const std::string& rdg_name,
       const std::vector<std::string>& node_properties,
       const std::vector<std::string>& edge_properties);

  /// Write the property graph to the given RDG name.
  ///
  /// \returns io_error if, for instance, a file already exists
  Result<void> Write(const std::string& rdg_name);

  /// Write the property graph to the given path.
  ///
  /// Like \ref Write(const std::string&) but overwrite the path this was read
  /// from (always an overwrite)
  ///
  /// \returns invalid if this was not read (but rather constructed in memory)
  Result<void> Write();

  std::shared_ptr<arrow::Schema> node_schema() const {
    return rdg_.node_table->schema();
  }

  std::shared_ptr<arrow::Schema> edge_schema() const {
    return rdg_.edge_table->schema();
  }

  std::shared_ptr<arrow::ChunkedArray> NodeProperty(int i) const {
    return rdg_.node_table->column(i);
  }

  std::shared_ptr<arrow::ChunkedArray> EdgeProperty(int i) const {
    return rdg_.edge_table->column(i);
  }

  const GraphTopology& topology() const { return topology_; }

  std::vector<std::shared_ptr<arrow::ChunkedArray>> NodeProperties() const {
    return rdg_.node_table->columns();
  }

  std::vector<std::shared_ptr<arrow::ChunkedArray>> EdgeProperties() const {
    return rdg_.edge_table->columns();
  }

  Result<void> AddNodeProperties(const std::shared_ptr<arrow::Table>& table);
  Result<void> AddEdgeProperties(const std::shared_ptr<arrow::Table>& table);

  Result<void> RemoveNodeProperty(int i);
  Result<void> RemoveEdgeProperty(int i);

  PropertyView node_property_view() {
    return PropertyView{
        .g                  = this,
        .schema_fn          = &PropertyFileGraph::node_schema,
        .property_fn        = &PropertyFileGraph::NodeProperty,
        .properties_fn      = &PropertyFileGraph::NodeProperties,
        .add_properties_fn  = &PropertyFileGraph::AddNodeProperties,
        .remove_property_fn = &PropertyFileGraph::RemoveNodeProperty,
    };
  }

  PropertyView edge_property_view() {
    return PropertyView{
        .g                  = this,
        .schema_fn          = &PropertyFileGraph::edge_schema,
        .property_fn        = &PropertyFileGraph::EdgeProperty,
        .properties_fn      = &PropertyFileGraph::EdgeProperties,
        .add_properties_fn  = &PropertyFileGraph::AddEdgeProperties,
        .remove_property_fn = &PropertyFileGraph::RemoveEdgeProperty,
    };
  }

  Result<void> SetTopology(const GraphTopology& topology);
};

} // namespace galois::graphs

#endif