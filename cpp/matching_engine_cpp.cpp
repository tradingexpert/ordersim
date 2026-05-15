#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "matching_engine_core.hpp"

namespace py = pybind11;

PYBIND11_MODULE(_matching_engine_cpp, module) {
    py::class_<FillRow>(module, "FillRow")
        .def_readonly("order_id", &FillRow::order_id)
        .def_readonly("side", &FillRow::side)
        .def_readonly("price_ticks", &FillRow::price_ticks)
        .def_readonly("size", &FillRow::size)
        .def_readonly("ts_ns", &FillRow::ts_ns);

    py::class_<MatchingEngineCpp>(module, "MatchingEngineCpp")
        .def(py::init<>())
        .def("apply_event", &MatchingEngineCpp::apply_event)
        .def("place_limit", &MatchingEngineCpp::place_limit)
        .def("place_market", &MatchingEngineCpp::place_market)
        .def("cancel", &MatchingEngineCpp::cancel)
        .def("book_top", &MatchingEngineCpp::book_top)
        .def("book_depth", &MatchingEngineCpp::book_depth)
        .def("position", &MatchingEngineCpp::position)
        .def("advance_time", &MatchingEngineCpp::advance_time)
        .def("own_orders", &MatchingEngineCpp::own_orders);
}
