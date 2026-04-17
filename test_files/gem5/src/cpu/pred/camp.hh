#ifndef __CPU_PRED_CAMP_HH__
#define __CPU_PRED_CAMP_HH__

#include <vector>

#include "base/sat_counter.hh"
#include "base/types.hh"
#include "cpu/pred/conditional.hh"
#include "params/CAMP.hh"

namespace gem5
{

namespace branch_prediction
{

class CAMP : public ConditionalPredictor
{
  public:
    CAMP(const CAMPParams &params);

    bool lookup(ThreadID tid, Addr pc, void * &bp_history) override;
    void updateHistories(ThreadID tid, Addr pc, bool uncond, bool taken,
                         Addr target, const StaticInstPtr &inst,
                         void * &bp_history) override;
    void update(ThreadID tid, Addr pc, bool taken, void * &bp_history,
                bool squashed, const StaticInstPtr &inst,
                Addr target) override;
    void squash(ThreadID tid, void * &bp_history) override;

  private:
    struct BPHistory
    {
        void *simpleHistory = nullptr;
        void *complexHistory = nullptr;
        unsigned confidenceIdx = 0;
        bool useComplex = false;
    };

    unsigned getConfidenceIndex(Addr pc) const;
    bool useComplexPredictor(uint8_t counter_value) const;

    ConditionalPredictor *simpleBP;
    ConditionalPredictor *complexBP;

    const unsigned confidenceTableEntries;
    const unsigned counterBits;
    const unsigned mlpWindowStates;
    const unsigned effectiveWindowStates;
    const unsigned confidenceIndexMask;
    const uint8_t complexWindowLower;
    const uint8_t complexWindowUpper;

    // gem5's LocalBP does not expose raw counter values, so CAMP mirrors the
    // same PC-indexed saturating table to derive confidence decisions.
    std::vector<SatCounter8> confidenceCtrs;
};

} // namespace branch_prediction
} // namespace gem5

#endif // __CPU_PRED_CAMP_HH__
