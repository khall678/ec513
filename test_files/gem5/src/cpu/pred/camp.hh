/*EC513 final project (Confidence-Aware Multiperspective Perceptron)
 * This header defines the CAMP branch predictor. It inherits all the heavy aspects
 *from the MultiperspectivePerceptron but adds a lightweight Bimodal (2 or 3 bit) state machine
 *To act as a power-saving filter
 */

#ifndef __CPU_PRED_CAMP_HH__
#define __CPU_PRED_CAMP_HH__

#include <vector>

// Bring in gem5 saturating counters (used for bimodal table)
#include "base/sat_counter.hh"

// Bring in multiperspective perceptron
#include "cpu/pred/multiperspective_perceptron_8KB.hh"

// Bring in parameters set in BranchPRedictor.py
#include "params/CAMP.hh"

namespace gem5
{

namespace branch_prediction
{

// CAMP is a MPP because it inherits the mutlispectrive perceptron but it has extra features
class CAMP : public MultiperspectivePerceptron8KB
{
 public:
   // Constructor when gem5 launches
   CAMP(const CAMPParams &params);
   
   // Runs during CPU fetch stage. CPU asks predictor for a guess
   bool lookup(ThreadID tid, Addr branch_addr, void * &bp_history) override;
   
   // Called after the CPU actually executed the branch and knows the real outcome
   void update(ThreadID tid, Addr branch_addr, bool taken, void * &bp_history, bool squashed,
	       const StaticInstPtr & inst, Addr target) override;

 private:
   //Find which counter belongs to the current branch instruction
   inline unsigned getFilterIndex(Addr branch_addr);
   
   // Reads the counter and translates it into Taken/Not Taken prediction
   inline bool getBimodalPrediction(uint8_t count);

  // HW parameters from the python file
  const unsigned filterPredictorSize; // Total budget in bits/bytes for filter
  const unsigned filterCtrBits;       // Size of each counter (2 bits or 3 bits)
  const unsigned filterPredictorSets; //Total number of counters we can fit
  const unsigned indexMask;           // Used for array indexing that is safe

  // Vector that acts as actual SRAM on the chip holding the counters
  std::vector<SatCounter8> confidenceCtrs;
};

} // namespace branch_prediction
} // namespace gem5

#endif





 