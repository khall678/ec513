from m5.objects.BranchPredictor import (
    ConditionalPredictor,
    LocalBP,
    MultiperspectivePerceptron64KB,
)
from m5.params import *
from m5.proxy import *


class CAMP(ConditionalPredictor):
    type = "CAMP"
    cxx_class = "gem5::branch_prediction::CAMP"
    cxx_header = "cpu/pred/camp.hh"

    confidenceTableSize = Param.Unsigned(
        8192, "Number of entries in the CAMP confidence table"
    )
    counterBits = Param.Unsigned(
        2, "Number of bits per CAMP confidence counter"
    )
    mlpWindowStates = Param.Unsigned(
        2,
        "Number of centered confidence states that delegate to the MLP",
    )

    simple_bp = Param.ConditionalPredictor(
        LocalBP(
            localPredictorSize=Parent.confidenceTableSize,
            localCtrBits=Parent.counterBits,
        ),
        "Simple bimodal predictor used outside the CAMP confidence window",
    )
    complex_bp = Param.ConditionalPredictor(
        MultiperspectivePerceptron64KB(),
        "Complex MLP predictor used inside the CAMP confidence window",
    )
