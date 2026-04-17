#include "cpu/pred/camp.hh"

#include <algorithm>

#include "base/intmath.hh"
#include "base/logging.hh"

namespace gem5
{

namespace branch_prediction
{

namespace
{

unsigned
sanitizeCounterBits(unsigned counter_bits)
{
    return std::clamp(counter_bits, 1U, 8U);
}

unsigned
sanitizeWindowStates(unsigned window_states)
{
    return std::max(window_states, 1U);
}

unsigned
computeEffectiveWindowStates(unsigned counter_bits, unsigned window_states)
{
    const unsigned safe_counter_bits = sanitizeCounterBits(counter_bits);
    const unsigned safe_window_states = sanitizeWindowStates(window_states);
    return std::min(safe_window_states, 1U << safe_counter_bits);
}

} // anonymous namespace

CAMP::CAMP(const CAMPParams &params)
    : ConditionalPredictor(params),
      simpleBP(params.simple_bp),
      complexBP(params.complex_bp),
      confidenceTableEntries(params.confidenceTableSize),
      counterBits(sanitizeCounterBits(params.counterBits)),
      mlpWindowStates(sanitizeWindowStates(params.mlpWindowStates)),
      effectiveWindowStates(
          computeEffectiveWindowStates(
              params.counterBits, params.mlpWindowStates)),
      confidenceIndexMask(confidenceTableEntries - 1),
      complexWindowLower(
          ((1U << counterBits) - effectiveWindowStates + 1) / 2),
      complexWindowUpper(complexWindowLower + effectiveWindowStates - 1),
      confidenceCtrs(confidenceTableEntries, SatCounter8(counterBits))
{
    if (!isPowerOf2(confidenceTableEntries)) {
        fatal("CAMP confidenceTableSize must be a power-of-two entry count.\n");
    }

    if (params.counterBits == 0 || params.counterBits > 8) {
        fatal("CAMP counterBits must be in the range [1, 8].\n");
    }

    if (params.mlpWindowStates == 0) {
        fatal("CAMP mlpWindowStates must be at least 1.\n");
    }
}

unsigned
CAMP::getConfidenceIndex(Addr pc) const
{
    return (pc >> instShiftAmt) & confidenceIndexMask;
}

bool
CAMP::useComplexPredictor(uint8_t counter_value) const
{
    return counter_value >= complexWindowLower &&
           counter_value <= complexWindowUpper;
}

bool
CAMP::lookup(ThreadID tid, Addr pc, void * &bp_history)
{
    const unsigned confidence_idx = getConfidenceIndex(pc);
    const uint8_t counter_value = confidenceCtrs[confidence_idx];
    const bool use_complex = useComplexPredictor(counter_value);

    void *simple_history = nullptr;
    void *complex_history = nullptr;

    const bool simple_pred = simpleBP->lookup(tid, pc, simple_history);
    const bool complex_pred = complexBP->lookup(tid, pc, complex_history);

    auto *history = new BPHistory;
    history->simpleHistory = simple_history;
    history->complexHistory = complex_history;
    history->confidenceIdx = confidence_idx;
    history->useComplex = use_complex;
    bp_history = history;

    return use_complex ? complex_pred : simple_pred;
}

void
CAMP::updateHistories(ThreadID tid, Addr pc, bool uncond, bool taken,
                      Addr target, const StaticInstPtr &inst,
                      void * &bp_history)
{
    BPHistory *history = nullptr;
    if (uncond) {
        history = new BPHistory;
        bp_history = history;
    } else {
        assert(bp_history);
        history = static_cast<BPHistory *>(bp_history);
    }

    simpleBP->updateHistories(
        tid, pc, uncond, taken, target, inst, history->simpleHistory);
    complexBP->updateHistories(
        tid, pc, uncond, taken, target, inst, history->complexHistory);
}

void
CAMP::update(ThreadID tid, Addr pc, bool taken, void * &bp_history,
             bool squashed, const StaticInstPtr &inst, Addr target)
{
    assert(bp_history);
    auto *history = static_cast<BPHistory *>(bp_history);

    simpleBP->update(
        tid, pc, taken, history->simpleHistory, squashed, inst, target);
    complexBP->update(
        tid, pc, taken, history->complexHistory, squashed, inst, target);

    if (!squashed && inst && inst->isCondCtrl()) {
        auto &counter = confidenceCtrs[history->confidenceIdx];
        if (taken) {
            counter++;
        } else {
            counter--;
        }
    }

    if (squashed) {
        return;
    }

    delete history;
    bp_history = nullptr;
}

void
CAMP::squash(ThreadID tid, void * &bp_history)
{
    assert(bp_history);
    auto *history = static_cast<BPHistory *>(bp_history);

    simpleBP->squash(tid, history->simpleHistory);
    complexBP->squash(tid, history->complexHistory);

    delete history;
    bp_history = nullptr;
}

} // namespace branch_prediction
} // namespace gem5
