#include "tiny_tree.h"

int tree_predict(const float* features) {
    if (features[1] <= 3.0f) {
        if (features[2] <= 5.0f) {
            if (features[4] <= 0.1f) {
                return 1;
            } else {
                return 0;
            }
        } else {
            return 1;
        }
    } else {
        return 1;
    }
}
