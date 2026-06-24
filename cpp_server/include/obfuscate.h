#pragma once
// Compile-time XOR string obfuscation.
// AY_OBFUSCATE("literal") → const char* decrypted on first access (static lifetime).
// Each call site gets a unique key via __COUNTER__ so no two strings share a keystream.

#include <cstddef>
#include <cstdint>

namespace ay {
namespace detail {

// splitmix64 — good avalanche, constexpr-friendly
constexpr uint64_t mix64(uint64_t h) noexcept {
    h ^= h >> 30;
    h *= UINT64_C(0xbf58476d1ce4e5b9);
    h ^= h >> 27;
    h *= UINT64_C(0x94d049bb133111eb);
    return h ^ (h >> 31);
}

// One key byte per (master-key, position) pair
constexpr char key_byte(uint64_t k, size_t i) noexcept {
    return static_cast<char>(
        mix64(k + static_cast<uint64_t>(i) * UINT64_C(0x9e3779b97f4a7c15)) & 0xFF);
}

} // namespace detail

// N includes the null terminator; K is the per-string key.
template <size_t N, uint64_t K>
class obfuscated {
    mutable char buf_[N];
    mutable bool live_ = false;
public:
    // constexpr ctor — compiler stores the XOR-encrypted bytes in .data, not plaintext.
    constexpr obfuscated(const char (&src)[N]) noexcept : buf_{}, live_(false) {
        for (size_t i = 0; i < N; ++i)
            buf_[i] = src[i] ^ detail::key_byte(K, i);
    }

    // noinline + volatile write stops the optimiser from constant-folding through the XOR.
    __attribute__((noinline))
    const char* get() const noexcept {
        if (!live_) {
            volatile char* p = buf_;
            for (size_t i = 0; i < N; ++i)
                p[i] = static_cast<char>(p[i] ^ detail::key_byte(K, i));
            live_ = true;
        }
        return buf_;
    }

    operator const char*() const noexcept { return get(); }
};

} // namespace ay

// Base key — change this constant to re-encrypt every string site at once.
#ifndef AY_OBFUSCATE_KEY
#define AY_OBFUSCATE_KEY UINT64_C(0xDEADBEEFCAFEBABE)
#endif

// Per-call unique key derived from base + call-site counter (LCG step).
#define AY_OBFUSCATE(str) \
    ([]() noexcept -> const char* { \
        constexpr uint64_t _k = \
            (AY_OBFUSCATE_KEY ^ (static_cast<uint64_t>(__COUNTER__) \
                                 * UINT64_C(6364136223846793005))) \
            + UINT64_C(1442695040888963407); \
        static ay::obfuscated<sizeof(str), _k> _o{str}; \
        return _o.get(); \
    }())
