/*EC513 final project (Confidence-Aware Multiperspective Perceptron)
 * This header defines the CAMP branch predictor. It inherits all the heavy aspects
 *from the MultiperspectivePerceptron but adds a lightweight Bimodal (2 or 3 bit) state machine
 *To act as a power-saving filter
 */

#include "cpu/pred/camp.hh"

#include "base/intmath.hh"
#include "base/logging.hh"
#include "base/trace.hh"
#include "debug/Fetch.hh"

namespace gem5
{
  namespace branch_prediction
  {
    //Constructor builds the hardware table
    CAMP::CAMP(const CAMPParams &params)
      : MultiperspectivePerceptron8KB(params), // start up the perceptron first
	filterPredictorSize(params.filter_predictor_size),
	filterCtrBits(params.filter_ctr_bits),

	// Calculate the number of entries we have by dividing total size by counter size
	filterPredictorSets(params.filter_predictor_size / params.filter_ctr_bits),

	// Creating bitmask of 1s to prevent index from going past array bounds
	indexMask(filterPredictorSets - 1),

	// Physically allocate sw array to act as saturating counters
	confidenceCtrs(filterPredictorSets, SatCounter8(params.filter_ctr_bits))

    {
      //Make sure table size power of 2 for bitwise math to work
      if (!isPowerOf2(filterPredictorSize)) {
	fatal("Invalid CAMP filter predictor size!\n");
      }
      if(!isPowerOf2(filterPredictorSets)) {
	fatal("Invalid number of CAMP filter sets! Check filterCtrBits. \n");
      }
    }

    // Helper function to find the counter
    inline unsigned
    CAMP::getFilterIndex(Addr branch_addr)
    {
      // Instrs are usually 4 bytes long. Last two bits are always 0. Shift right to throw away these bits
      // then apply mask to get a safe array index
      return (branch_addr >> instShiftAmt) & indexMask;
    }

    // Helper function to read the counter
    inline bool
    CAMP::getBimodalPrediction(uint8_t count)
    {
      //Only care about MSB. For a 2 bit counter, shifting right by 1 gives us
      //0 or 1 --> 0 (NT)
      //2 or 3 --> 1 (T)
      return (count >>(filterCtrBits -1));
    }

    //Make the prediction
    bool
    CAMP::lookup(ThreadID tid, Addr branch_addr, void * &bp_history)
    {
      // First, wWe call the perceptron to safely allocate its memeory
      // In real hw, this big compute area would have its voltage shut off
      // In the sumulator, we still call it to prevent memory crashes

      bool mpp_prediction = MultiperspectivePerceptron8KB::lookup(tid, branch_addr, bp_history);

      // Next, look up branch in bimodal table. Take mem address and hash it to find specific count
      //on SRAM table
      unsigned filter_idx = getFilterIndex(branch_addr);
      uint8_t counter_val = confidenceCtrs[filter_idx];

      // Then, Calculate the unconfident middle area dynamically
      // If filterCtrBits = 2 (Max 3): Middle is 1 and 2
      // If filterCtrBits = 3 (Max 7): Middle is 2, 3, 4, and 5
      uint8_t max_val = (1<<filterCtrBits)-1;
      uint8_t lower_threshold = max_val / 4;
      uint8_t upper_threshold = max_val - lower_threshold -1;

      bool is_unconfident = (counter_val > lower_threshold) && (counter_val <=upper_threshold);

      // Make routing decision
      if (is_unconfident) {
	// Trust perceptron
	return mpp_prediction;
      } else {
	// Save power and use simple Bimodal
	return getBimodalPrediction(counter_val);
      }
    }

    // Update weights in commit stage of pipeline
    void
    CAMP::update(ThreadID tid, Addr branch_addr, bool taken, void *&bp_history, bool squashed,
		 const StaticInstPtr & inst, Addr target)
    {
      // First, find the counter again to see what state we are in
      unsigned filter_idx = getFilterIndex(branch_addr);

      // Next, re-calculate if the perceptron was awake during lookup phase
      uint8_t max_val = (1<<filterCtrBits)-1;

      // Then, Train perceptron only if it was awake and working (now always, taking into account the squashed variable)
      MultiperspectivePerceptron8KB::update(tid, branch_addr, taken, bp_history, squashed, inst, target);

      // After all of that, handle mis-speculation. If CPU tells us branch should not have happened,
      // meaning it was executed down a wrong path, we exit here so bimodal does not learn bad data
      if (squashed) {
	return;
      }

      // Train bimodal filter
      if (taken) {
	// If branch taken, increment towards max val
	if (confidenceCtrs[filter_idx] < max_val) {
	  confidenceCtrs[filter_idx]++;
	}
      } else {
	// If branch not taken, decrement down towards 0
	if (confidenceCtrs[filter_idx] > 0) {
	  confidenceCtrs[filter_idx]--;
	}
      }
    }
    
  } // namespace branch_prediction
} //namespace gem5
