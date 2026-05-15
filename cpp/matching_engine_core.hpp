#pragma once

#include <algorithm>
#include <cstdint>
#include <deque>
#include <map>
#include <stdexcept>
#include <string>
#include <tuple>
#include <unordered_map>
#include <utility>
#include <vector>

struct Order {
    int64_t order_id;
    char side;
    int64_t price_ticks;
    int32_t size;
};

struct QueueEntry {
    bool own;
    int64_t order_id;
};

struct FillRow {
    int64_t order_id;
    char side;
    int64_t price_ticks;
    int32_t size;
    int64_t ts_ns;
};

class MatchingEngineCpp {
public:
    std::vector<FillRow> apply_event(
        int64_t ts_ns,
        const std::string& action,
        char side,
        int64_t price_ticks,
        int32_t size,
        int64_t order_id
    ) {
        now_ns_ = ts_ns;
        const size_t before = passive_fills_.size();

        if (action == "add") {
            add_public(order_id, side, price_ticks, size);
        } else if (action == "cancel") {
            cancel_public(order_id, side, price_ticks, size);
        } else if (action == "modify") {
            modify_public(order_id, side, price_ticks, size);
        } else if (action == "trade") {
            consume_level(side, price_ticks, size, ts_ns);
        } else {
            throw std::runtime_error("unknown MBO action");
        }

        return std::vector<FillRow>(
            passive_fills_.begin() + static_cast<std::ptrdiff_t>(before),
            passive_fills_.end()
        );
    }

    std::tuple<int64_t, std::vector<FillRow>> place_limit(
        char side,
        int64_t price_ticks,
        int32_t size,
        const std::string& tif
    ) {
        validate_order(size, price_ticks);
        const int64_t order_id = allocate_order_id();
        auto [fills, remaining] = match_active_order(
            order_id,
            side,
            size,
            price_ticks,
            true
        );

        int64_t resting_order_id = -1;
        if (remaining > 0 && tif == "GTC") {
            const char resting_side = book_side_for_order_side(side);
            add_own(order_id, resting_side, price_ticks, remaining);
            resting_order_id = order_id;
        }
        return {resting_order_id, fills};
    }

    std::vector<FillRow> place_market(char side, int32_t size) {
        validate_order(size, 1);
        const int64_t order_id = allocate_order_id();
        auto [fills, ignored_remaining] = match_active_order(
            order_id,
            side,
            size,
            0,
            false
        );
        (void)ignored_remaining;
        return fills;
    }

    bool cancel(int64_t order_id) {
        auto own_it = own_orders_.find(order_id);
        if (own_it == own_orders_.end()) return false;

        const Order order = own_it->second;
        own_orders_.erase(own_it);
        remove_from_book(order.side, order.price_ticks, order.size);
        remove_from_queue(order.side, order.price_ticks, true, order.order_id);
        return true;
    }

    std::pair<int64_t, int64_t> book_top() const {
        const int64_t bid = bids_.empty() ? missing_price() : bids_.rbegin()->first;
        const int64_t ask = asks_.empty() ? missing_price() : asks_.begin()->first;
        return {bid, ask};
    }

    std::pair<
        std::vector<std::pair<int64_t, int32_t>>,
        std::vector<std::pair<int64_t, int32_t>>
    > book_depth(int levels) const {
        std::vector<std::pair<int64_t, int32_t>> bids;
        std::vector<std::pair<int64_t, int32_t>> asks;
        bids.reserve(levels);
        asks.reserve(levels);

        for (
            auto it = bids_.rbegin();
            it != bids_.rend() && (int)bids.size() < levels;
            ++it
        ) {
            bids.emplace_back(it->first, it->second);
        }
        for (
            auto it = asks_.begin();
            it != asks_.end() && (int)asks.size() < levels;
            ++it
        ) {
            asks.emplace_back(it->first, it->second);
        }
        return {bids, asks};
    }

    int64_t position() const { return position_; }

    void advance_time(int64_t ts_ns) {
        if (ts_ns < now_ns_) {
            throw std::runtime_error("cannot move engine time backwards");
        }
        now_ns_ = ts_ns;
    }

    std::vector<std::tuple<int64_t, char, int64_t, int32_t, int32_t>>
    own_orders() {
        std::vector<std::tuple<int64_t, char, int64_t, int32_t, int32_t>> rows;
        rows.reserve(own_orders_.size());
        std::vector<int64_t> ids;
        ids.reserve(own_orders_.size());
        for (const auto& item : own_orders_) ids.push_back(item.first);
        std::sort(ids.begin(), ids.end());

        for (int64_t order_id : ids) {
            const Order& order = own_orders_.at(order_id);
            rows.emplace_back(
                order.order_id,
                order.side,
                order.price_ticks,
                order.size,
                queue_ahead(order.side, order.price_ticks, order.order_id)
            );
        }
        return rows;
    }

private:
    std::map<int64_t, int32_t> bids_;
    std::map<int64_t, int32_t> asks_;
    std::unordered_map<int64_t, Order> public_orders_;
    std::unordered_map<int64_t, Order> own_orders_;
    std::map<std::pair<char, int64_t>, std::deque<QueueEntry>> queues_;
    std::vector<FillRow> passive_fills_;
    int64_t next_order_id_ = 1'000'000'000;
    int64_t now_ns_ = 0;
    int64_t position_ = 0;

    static constexpr int64_t missing_price() { return -1; }

    static void validate_order(int32_t size, int64_t price_ticks) {
        if (size <= 0) throw std::runtime_error("size must be positive");
        if (price_ticks <= 0) throw std::runtime_error("price must be positive");
    }

    int64_t allocate_order_id() { return next_order_id_++; }

    static char book_side_for_order_side(char side) {
        return side == 'B' ? 'B' : 'A';
    }

    static char opposite_book_side(char side) {
        return side == 'B' ? 'A' : 'B';
    }

    static char opposite_order_side(char book_side) {
        return book_side == 'B' ? 'B' : 'A';
    }

    std::map<int64_t, int32_t>& book_for_side(char side) {
        return side == 'B' ? bids_ : asks_;
    }

    const std::map<int64_t, int32_t>& book_for_side(char side) const {
        return side == 'B' ? bids_ : asks_;
    }

    std::deque<QueueEntry>& queue(char side, int64_t price_ticks) {
        return queues_[{side, price_ticks}];
    }

    void add_to_book(char side, int64_t price_ticks, int32_t size) {
        auto& book = book_for_side(side);
        book[price_ticks] += size;
        if (book[price_ticks] <= 0) book.erase(price_ticks);
    }

    void remove_from_book(char side, int64_t price_ticks, int32_t size) {
        auto& book = book_for_side(side);
        auto it = book.find(price_ticks);
        if (it == book.end()) return;
        it->second -= size;
        if (it->second <= 0) book.erase(it);
    }

    void add_public(int64_t order_id, char side, int64_t price_ticks, int32_t size) {
        public_orders_[order_id] = Order{order_id, side, price_ticks, size};
        queue(side, price_ticks).push_back(QueueEntry{false, order_id});
        add_to_book(side, price_ticks, size);
    }

    void cancel_public(
        int64_t order_id,
        char side,
        int64_t price_ticks,
        int32_t size
    ) {
        auto it = public_orders_.find(order_id);
        if (it == public_orders_.end()) {
            remove_from_book(side, price_ticks, size);
            return;
        }

        Order& order = it->second;
        const int32_t cancelled = std::min(order.size, size);
        order.size -= cancelled;
        remove_from_book(order.side, order.price_ticks, cancelled);
        if (order.size == 0) {
            const Order removed = order;
            public_orders_.erase(it);
            remove_from_queue(removed.side, removed.price_ticks, false, order_id);
        }
    }

    void modify_public(
        int64_t order_id,
        char side,
        int64_t price_ticks,
        int32_t size
    ) {
        auto it = public_orders_.find(order_id);
        if (it == public_orders_.end()) {
            add_public(order_id, side, price_ticks, size);
            return;
        }

        Order& order = it->second;
        const bool same_level = order.side == side && order.price_ticks == price_ticks;
        if (same_level) {
            const int32_t delta = size - order.size;
            if (delta > 0) add_to_book(order.side, order.price_ticks, delta);
            if (delta < 0) remove_from_book(order.side, order.price_ticks, -delta);
            order.size = size;
            if (order.size == 0) {
                const Order removed = order;
                public_orders_.erase(it);
                remove_from_queue(removed.side, removed.price_ticks, false, order_id);
            }
            return;
        }

        const Order old = order;
        remove_from_book(old.side, old.price_ticks, old.size);
        remove_from_queue(old.side, old.price_ticks, false, order_id);
        order.side = side;
        order.price_ticks = price_ticks;
        order.size = size;
        queue(side, price_ticks).push_back(QueueEntry{false, order_id});
        add_to_book(side, price_ticks, size);
    }

    void add_own(int64_t order_id, char side, int64_t price_ticks, int32_t size) {
        own_orders_[order_id] = Order{order_id, side, price_ticks, size};
        queue(side, price_ticks).push_back(QueueEntry{true, order_id});
        add_to_book(side, price_ticks, size);
    }

    std::pair<std::vector<FillRow>, int32_t> match_active_order(
        int64_t order_id,
        char order_side,
        int32_t size,
        int64_t limit_price_ticks,
        bool has_limit
    ) {
        std::vector<FillRow> fills;
        int32_t remaining = size;
        const char book_side = opposite_book_side(order_side);
        const auto prices = matchable_prices(book_side, limit_price_ticks, has_limit);

        for (int64_t price_ticks : prices) {
            if (remaining == 0) break;
            const int32_t level_size = book_for_side(book_side).at(price_ticks);
            const int32_t trade_size = std::min(remaining, level_size);
            consume_level(book_side, price_ticks, trade_size, now_ns_);
            fills.push_back(FillRow{order_id, order_side, price_ticks, trade_size, now_ns_});
            position_ += order_side == 'B' ? trade_size : -trade_size;
            remaining -= trade_size;
        }
        return {fills, remaining};
    }

    std::vector<int64_t> matchable_prices(
        char side,
        int64_t limit_price_ticks,
        bool has_limit
    ) const {
        std::vector<int64_t> prices;
        const auto& book = book_for_side(side);
        if (side == 'A') {
            for (const auto& [price_ticks, ignored_size] : book) {
                (void)ignored_size;
                if (!has_limit || price_ticks <= limit_price_ticks) {
                    prices.push_back(price_ticks);
                }
            }
        } else {
            for (auto it = book.rbegin(); it != book.rend(); ++it) {
                if (!has_limit || it->first >= limit_price_ticks) {
                    prices.push_back(it->first);
                }
            }
        }
        return prices;
    }

    void consume_level(char side, int64_t price_ticks, int32_t size, int64_t ts_ns) {
        int32_t remaining = size;
        auto key = std::make_pair(side, price_ticks);
        auto queue_it = queues_.find(key);
        if (queue_it == queues_.end()) return;

        auto& entries = queue_it->second;
        while (remaining > 0 && !entries.empty()) {
            const QueueEntry entry = entries.front();
            const int32_t consumed = entry.own
                ? consume_own_entry(entry.order_id, side, price_ticks, remaining, ts_ns)
                : consume_public_entry(entry.order_id, side, price_ticks, remaining);

            remaining -= consumed;
            if (consumed == 0) entries.pop_front();
        }

        if (entries.empty()) queues_.erase(key);
    }

    int32_t consume_public_entry(
        int64_t order_id,
        char side,
        int64_t price_ticks,
        int32_t available_size
    ) {
        auto it = public_orders_.find(order_id);
        if (it == public_orders_.end()) return 0;

        Order& order = it->second;
        const int32_t consumed = std::min(order.size, available_size);
        order.size -= consumed;
        remove_from_book(side, price_ticks, consumed);
        if (order.size == 0) {
            public_orders_.erase(it);
            queue(side, price_ticks).pop_front();
        }
        return consumed;
    }

    int32_t consume_own_entry(
        int64_t order_id,
        char side,
        int64_t price_ticks,
        int32_t available_size,
        int64_t ts_ns
    ) {
        auto it = own_orders_.find(order_id);
        if (it == own_orders_.end()) return 0;

        Order& order = it->second;
        const int32_t consumed = std::min(order.size, available_size);
        order.size -= consumed;
        remove_from_book(side, price_ticks, consumed);
        passive_fills_.push_back(
            FillRow{order_id, opposite_order_side(side), price_ticks, consumed, ts_ns}
        );
        position_ += side == 'B' ? consumed : -consumed;

        if (order.size == 0) {
            own_orders_.erase(it);
            queue(side, price_ticks).pop_front();
        }
        return consumed;
    }

    int32_t queue_ahead(char side, int64_t price_ticks, int64_t order_id) {
        int32_t total = 0;
        for (const QueueEntry& entry : queue(side, price_ticks)) {
            if (entry.own && entry.order_id == order_id) return total;
            const auto& store = entry.own ? own_orders_ : public_orders_;
            auto it = store.find(entry.order_id);
            if (it != store.end()) total += it->second.size;
        }
        throw std::runtime_error("own order not found in queue");
    }

    void remove_from_queue(
        char side,
        int64_t price_ticks,
        bool own,
        int64_t order_id
    ) {
        auto key = std::make_pair(side, price_ticks);
        auto it = queues_.find(key);
        if (it == queues_.end()) return;
        auto& entries = it->second;
        entries.erase(
            std::remove_if(
                entries.begin(),
                entries.end(),
                [own, order_id](const QueueEntry& entry) {
                    return entry.own == own && entry.order_id == order_id;
                }
            ),
            entries.end()
        );
        if (entries.empty()) queues_.erase(it);
    }
};
