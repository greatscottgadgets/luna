// Copyright 2014 Technical Machine, Inc. See the COPYRIGHT
// file at the top-level directory of this distribution.
//
// Licensed under the Apache License, Version 2.0 <LICENSE-APACHE or
// http://www.apache.org/licenses/LICENSE-2.0> or the MIT license
// <LICENSE-MIT or http://opensource.org/licenses/MIT>, at your
// option. This file may not be copied, modified, or distributed
// except according to those terms.

#pragma once
#include "class/dfu/dfu.h"

#include "common/board.h"

#define GCLK_SYSTEM 0
#define DFU_INTF 0
#define DFU_TRANSFER_SIZE (FLASH_PAGE_SIZE * 4)
