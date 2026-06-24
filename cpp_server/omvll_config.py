"""
O-MVLL configuration for RBCheck.

Applies control-flow flattening and string encoding to the sensitive parsing
and handler functions only. The boring CRUD plumbing is intentionally left
untouched to keep the performance cost low.

To enable:
  1. Install O-MVLL for AArch64/Mach-O:
       https://obfuscator.re/omvll/installation/
  2. Locate the plugin dylib (e.g. /opt/omvll/lib/omvll.dylib).
  3. Reconfigure CMake:
       cmake -DENABLE_OMVLL=ON -DOMVLL_LIB=/opt/omvll/lib/omvll.dylib ..
  4. Rebuild.

O-MVLL docs: https://obfuscator.re/omvll
"""

import omvll

# Functions that receive control-flow flattening
CFF_TARGETS = {
    "parseTransaction",
    "transactionAnalysis",
    "getByDate",
    "getWeekly",
    "getPast7Days",
    "getMonthly",
    "getBiweekly",
    "getDateRange",
    "getByMerchant",
    "getByAmtRange",
    "create",
    "getById",
    "updateById",
}


class ObfuscationConfig(omvll.ObfuscationConfig):
    def flatten_cfg(self, mod, func):
        return func.name in CFF_TARGETS

    def obfuscate_string(self, mod, func, string):
        # Encode strings inside sensitive functions (belt-and-suspenders on top
        # of the compile-time XOR obfuscation already applied by obfuscate.h).
        if func.name in CFF_TARGETS:
            return omvll.StringEncOptStack(loopLevel=2)
        return False
