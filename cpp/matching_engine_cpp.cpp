#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include "matching_engine_core.hpp"

namespace py = pybind11;

namespace {

struct BatchBuffers {
    py::ssize_t n;
    const int64_t* ts_ns;
    const uint8_t* action;
    const uint8_t* side;
    const int64_t* price_ticks;
    const int32_t* size;
    const int64_t* order_id;
};

struct MarkRow {
    int64_t ts_ns;
    int64_t bid_ticks;
    int64_t ask_ticks;
};

template <typename T>
const T* checked_buffer(
    const py::buffer& buffer,
    const std::string& expected_format,
    const char* name,
    py::ssize_t expected_size = -1
) {
    const py::buffer_info info = buffer.request();
    if (info.ndim != 1) {
        throw py::value_error(std::string(name) + " must be one-dimensional");
    }
    if (info.itemsize != static_cast<py::ssize_t>(sizeof(T))
        || info.format != expected_format) {
        throw py::value_error(std::string(name) + " has the wrong dtype");
    }
    if (info.strides[0] != static_cast<py::ssize_t>(sizeof(T))) {
        throw py::value_error(std::string(name) + " must be contiguous");
    }
    if (expected_size >= 0 && info.shape[0] != expected_size) {
        throw py::value_error("batch columns must have equal length");
    }
    return static_cast<const T*>(info.ptr);
}

BatchBuffers read_batch_buffers(
    const py::buffer& ts_ns,
    const py::buffer& action,
    const py::buffer& side,
    const py::buffer& price_ticks,
    const py::buffer& size,
    const py::buffer& order_id
) {
    const py::buffer_info ts_info = ts_ns.request();
    if (ts_info.ndim != 1) {
        throw py::value_error("ts_ns must be one-dimensional");
    }
    if (ts_info.itemsize != static_cast<py::ssize_t>(sizeof(int64_t))
        || ts_info.format != py::format_descriptor<int64_t>::format()) {
        throw py::value_error("ts_ns has the wrong dtype");
    }
    if (ts_info.strides[0] != static_cast<py::ssize_t>(sizeof(int64_t))) {
        throw py::value_error("ts_ns must be contiguous");
    }

    const py::ssize_t n = ts_info.shape[0];
    return BatchBuffers{
        n,
        static_cast<const int64_t*>(ts_info.ptr),
        checked_buffer<uint8_t>(
            action,
            py::format_descriptor<uint8_t>::format().c_str(),
            "action",
            n
        ),
        checked_buffer<uint8_t>(
            side,
            py::format_descriptor<uint8_t>::format().c_str(),
            "side",
            n
        ),
        checked_buffer<int64_t>(
            price_ticks,
            py::format_descriptor<int64_t>::format().c_str(),
            "price_ticks",
            n
        ),
        checked_buffer<int32_t>(
            size,
            py::format_descriptor<int32_t>::format().c_str(),
            "size",
            n
        ),
        checked_buffer<int64_t>(
            order_id,
            py::format_descriptor<int64_t>::format().c_str(),
            "order_id",
            n
        ),
    };
}

std::vector<FillRow> apply_events_batch(
    MatchingEngineCpp& engine,
    const py::buffer& ts_ns,
    const py::buffer& action,
    const py::buffer& side,
    const py::buffer& price_ticks,
    const py::buffer& size,
    const py::buffer& order_id
) {
    const BatchBuffers batch = read_batch_buffers(
        ts_ns,
        action,
        side,
        price_ticks,
        size,
        order_id
    );

    std::vector<FillRow> fills;

    for (py::ssize_t i = 0; i < batch.n; ++i) {
        const auto event_fills = engine.apply_event_code(
            batch.ts_ns[i],
            static_cast<char>(batch.action[i]),
            static_cast<char>(batch.side[i]),
            batch.price_ticks[i],
            batch.size[i],
            batch.order_id[i]
        );
        fills.insert(fills.end(), event_fills.begin(), event_fills.end());
    }

    return fills;
}

py::tuple apply_events_batch_with_marks(
    MatchingEngineCpp& engine,
    const py::buffer& ts_ns,
    const py::buffer& action,
    const py::buffer& side,
    const py::buffer& price_ticks,
    const py::buffer& size,
    const py::buffer& order_id
) {
    const BatchBuffers batch = read_batch_buffers(
        ts_ns,
        action,
        side,
        price_ticks,
        size,
        order_id
    );

    std::vector<FillRow> fills;
    std::vector<MarkRow> marks;

    for (py::ssize_t i = 0; i < batch.n; ++i) {
        const auto event_fills = engine.apply_event_code(
            batch.ts_ns[i],
            static_cast<char>(batch.action[i]),
            static_cast<char>(batch.side[i]),
            batch.price_ticks[i],
            batch.size[i],
            batch.order_id[i]
        );
        fills.insert(fills.end(), event_fills.begin(), event_fills.end());

        const auto [bid_ticks, ask_ticks] = engine.book_top();
        if (bid_ticks >= 0 && ask_ticks >= 0) {
            marks.push_back(MarkRow{batch.ts_ns[i], bid_ticks, ask_ticks});
        }
    }

    return py::make_tuple(fills, marks);
}

py::tuple apply_events_until_fill(
    MatchingEngineCpp& engine,
    const py::buffer& ts_ns,
    const py::buffer& action,
    const py::buffer& side,
    const py::buffer& price_ticks,
    const py::buffer& size,
    const py::buffer& order_id
) {
    const BatchBuffers batch = read_batch_buffers(
        ts_ns,
        action,
        side,
        price_ticks,
        size,
        order_id
    );

    std::vector<FillRow> fills;

    for (py::ssize_t i = 0; i < batch.n; ++i) {
        const auto event_fills = engine.apply_event_code(
            batch.ts_ns[i],
            static_cast<char>(batch.action[i]),
            static_cast<char>(batch.side[i]),
            batch.price_ticks[i],
            batch.size[i],
            batch.order_id[i]
        );
        if (!event_fills.empty()) {
            fills.insert(fills.end(), event_fills.begin(), event_fills.end());
            return py::make_tuple(i + 1, fills);
        }
    }

    return py::make_tuple(batch.n, fills);
}

}  // namespace

PYBIND11_MODULE(_matching_engine_cpp, module) {
    py::class_<FillRow>(module, "FillRow")
        .def_readonly("order_id", &FillRow::order_id)
        .def_readonly("side", &FillRow::side)
        .def_readonly("price_ticks", &FillRow::price_ticks)
        .def_readonly("size", &FillRow::size)
        .def_readonly("ts_ns", &FillRow::ts_ns);

    py::class_<MarkRow>(module, "MarkRow")
        .def_readonly("ts_ns", &MarkRow::ts_ns)
        .def_readonly("bid_ticks", &MarkRow::bid_ticks)
        .def_readonly("ask_ticks", &MarkRow::ask_ticks);

    py::class_<MatchingEngineCpp>(module, "MatchingEngineCpp")
        .def(py::init<>())
        .def("apply_event", &MatchingEngineCpp::apply_event)
        .def("apply_events_batch", &apply_events_batch)
        .def("apply_events_batch_with_marks", &apply_events_batch_with_marks)
        .def("apply_events_until_fill", &apply_events_until_fill)
        .def("place_limit", &MatchingEngineCpp::place_limit)
        .def("place_market", &MatchingEngineCpp::place_market)
        .def("cancel", &MatchingEngineCpp::cancel)
        .def("book_top", &MatchingEngineCpp::book_top)
        .def("book_depth", &MatchingEngineCpp::book_depth)
        .def("position", &MatchingEngineCpp::position)
        .def("advance_time", &MatchingEngineCpp::advance_time)
        .def("own_orders", &MatchingEngineCpp::own_orders);
}
