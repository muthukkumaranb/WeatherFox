#include "tiny_tree.h"

int tree_predict(const float* features) {
    if (features[1] <= 3.0409239530563354f) {
        if (features[1] <= -2.9794727563858032f) {
            return 1;
        } else {
            return 0;
        }
    } else {
        return 1;
    }
}
