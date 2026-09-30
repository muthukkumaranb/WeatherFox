#include "tiny_tree.h"

int tree_predict(const float* features) {
    if (features[3] <= -2.4849998950958252f) {
        if (features[1] <= 4.0050001144409180f) {
            if (features[1] <= -7.0150001049041748f) {
                if (features[0] <= -13.0799999237060547f) {
                    return 0;
                } else {
                    if (features[0] <= -11.0050001144409180f) {
                        if (features[1] <= -12.6199998855590820f) {
                            return 0;
                        } else {
                            return 1;
                        }
                    } else {
                        if (features[1] <= -8.6100001335144043f) {
                            return 0;
                        } else {
                            return 1;
                        }
                    }
                }
            } else {
                if (features[1] <= 3.4950000047683716f) {
                    if (features[2] <= 2.5000000000000000f) {
                        return 0;
                    } else {
                        return 1;
                    }
                } else {
                    if (features[2] <= 1.5000000000000000f) {
                        if (features[3] <= -13.0650000572204590f) {
                            return 1;
                        } else {
                            return 0;
                        }
                    } else {
                        return 1;
                    }
                }
            }
        } else {
            if (features[1] <= 5.0899999141693115f) {
                if (features[3] <= -9.7349996566772461f) {
                    if (features[0] <= 5.0200002193450928f) {
                        if (features[0] <= 4.2900002002716064f) {
                            return 0;
                        } else {
                            return 0;
                        }
                    } else {
                        return 0;
                    }
                } else {
                    if (features[3] <= -9.5049996376037598f) {
                        if (features[0] <= 4.6800000667572021f) {
                            return 1;
                        } else {
                            return 1;
                        }
                    } else {
                        if (features[2] <= 1.5000000000000000f) {
                            return 0;
                        } else {
                            return 1;
                        }
                    }
                }
            } else {
                if (features[0] <= 12.9650001525878906f) {
                    if (features[0] <= 11.2049999237060547f) {
                        if (features[0] <= 8.9599995613098145f) {
                            return 1;
                        } else {
                            return 0;
                        }
                    } else {
                        if (features[0] <= 12.5750002861022949f) {
                            return 1;
                        } else {
                            return 1;
                        }
                    }
                } else {
                    return 0;
                }
            }
        }
    } else {
        return 1;
    }
}
