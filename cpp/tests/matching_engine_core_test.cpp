#include <cassert>
#include <iostream>

#include "../matching_engine_core.hpp"

void test_market_order_crosses_spread() {
    MatchingEngineCpp engine;
    engine.apply_event(1, "add", 'A', 1010, 2, 10);

    const auto fills = engine.place_market('B', 1);

    assert(fills.size() == 1);
    assert(fills[0].side == 'B');
    assert(fills[0].price_ticks == 1010);
    assert(fills[0].size == 1);
    assert(engine.position() == 1);
}

void test_passive_fill_respects_queue_ahead() {
    MatchingEngineCpp engine;
    engine.apply_event(1, "add", 'B', 1000, 2, 10);
    const auto [order_id, active_fills] = engine.place_limit('B', 1000, 1, "GTC");

    assert(active_fills.empty());
    assert(order_id >= 1'000'000'000);
    assert(std::get<4>(engine.own_orders()[0]) == 2);

    engine.apply_event(2, "trade", 'B', 1000, 2, 20);
    assert(engine.position() == 0);

    const auto passive_fills = engine.apply_event(3, "trade", 'B', 1000, 1, 21);
    assert(passive_fills.size() == 1);
    assert(passive_fills[0].order_id == order_id);
    assert(passive_fills[0].side == 'B');
    assert(engine.position() == 1);
}

void test_cancel_removes_own_order() {
    MatchingEngineCpp engine;
    const auto [order_id, fills] = engine.place_limit('B', 1000, 1, "GTC");

    assert(fills.empty());
    assert(engine.cancel(order_id));
    assert(engine.own_orders().empty());
    assert(!engine.cancel(order_id));
}

int main() {
    test_market_order_crosses_spread();
    test_passive_fill_respects_queue_ahead();
    test_cancel_removes_own_order();
    std::cout << "matching_engine_core tests passed\n";
}
