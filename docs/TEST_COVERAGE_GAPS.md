# Test Coverage Gaps Analysis

## Overview

Current overall coverage: **92%** (2069 total lines, 169 uncovered)

## Completed ✅

### 1. Configuration Reload (`reload.py`) - **100% coverage** ✅

**Status**: Fully tested

**Tests Added:**

- `tests/test_reload.py` - Complete test suite covering all success and error paths
- All reload scenarios tested: add, remove, no changes, error handling, metric cleanup

### 2. Reload HTTP Endpoint (`api.py`) - **100% coverage** ✅

**Status**: Fully tested

**Tests Added:**

- `tests/test_api_reload.py` - Complete endpoint test coverage
- Success, error, and FileNotFoundError scenarios tested

### 3. PollerManager Reload (`poller/manager.py`) - **96% coverage** ✅

**Status**: Fully tested

**Tests Added:**

- `tests/test_poller_manager_reload.py` - Complete reload_tasks() test coverage
- Add, remove, no changes, thread safety all tested

### 4. SIGHUP Signal Handling (`main.py`) - **55% coverage** ⚠️

**Status**: Partially tested

**Tests Added:**

- `tests/test_main_signals.py` - Basic signal handler tests
- **Remaining**: Lines 52-58 (run_servers error handling), 90 (if __name__ == "__main__")

**Impact**: Low - Core signal handling tested, edge cases remain

### 5. Reload Monitor Task (`app.py`) - **82% coverage** ✅

**Status**: Fully tested

**Tests Added:**

- `tests/test_app_reload_monitor.py` - Complete monitor task test coverage
- Event detection, success/failure paths, cancellation all tested

## Completed Additional Tests ✅

### 6. Poller Collect Error Paths (`poller/collect.py`) - **90% coverage** ✅

**Status**: Mostly tested

**Tests Added:**

- `tests/test_poller_collect.py` - Added tests for:
  - Web3 client creation failures
  - Account balance retrieval failures
  - Connection failures (already tested)
  - Error paths in `_record_chain_health_metrics()` (already tested)
- **Remaining**: Lines 242-253, 272-298 (edge cases in contract collection)

**Impact**: Low - Core error paths are well tested

### 7. RPC Error Handling (`rpc.py`) - **86% coverage** ✅

**Status**: Well tested

**Tests Added:**

- `tests/test_rpc_error_categorization.py` - Complete test suite for:
  - All error categorization paths in `_categorize_error()` (timeout, connection, RPC, value, unknown)
  - All wrapping scenarios in `_wrap_rpc_exception()` (preserves RpcError, wraps timeout/connection/RPC/value/unknown)
  - Web3RPCError handling with error codes
- **Remaining**: Lines 407-442, 493 (error handling paths in execute_with_retries, RuntimeError edge case)

**Impact**: Low - Error categorization and wrapping are fully tested

### 8. Context Helper Functions (`context.py`) - **100% coverage** ✅

**Status**: Fully tested

**Tests Added:**

- `tests/test_context.py` - Complete test suite for:
  - `default_rpc_factory()` function - connection pool usage
  - `create_default_context()` function - runtime settings loading
  - `get_application_context()` - lazy creation and caching
  - `set_application_context()` - context replacement
  - `reset_application_context()` - context clearing
  - `ApplicationContext` properties and methods

**Impact**: Low - Fully tested

### 9. App Warm Poll Edge Cases (`app.py`) - **88% coverage** ✅

**Status**: Mostly tested

**Tests Added:**

- `tests/test_app_warm_poll.py` - Complete test suite for:
  - Warm poll timeout scenarios
  - Warm poll error handling
  - Warm poll with multiple blockchains
  - Partial warm poll success/failure
  - Warm poll skipped when disabled
- **Remaining**: Lines 226-228, 262-263, 278-280, 289-291, 296-298, 309-311, 320-322, 374-375, 411-412 (shutdown edge cases)

**Impact**: Low - Core warm poll functionality is well tested

### 10. App Error Handling (`app.py`) - **88% coverage** ✅

**Status**: Mostly tested

**Tests Added:**

- `tests/test_app_error_handling.py` - Test suite for:
  - ValueError (config validation error) handling in lifespan
  - FileNotFoundError (config file not found) handling in lifespan
  - Warm poll exception handling
  - Shutdown exception handling
- **Remaining**: Lines 226-228, 262-263, 278-280, 289-291, 296-298, 309-311, 320-322, 374-375, 411-412 (shutdown edge cases)

**Impact**: Low - Core error handling is well tested

### 11. RPC Client Method Implementations (`rpc.py`) - **86% coverage** ✅

**Status**: Mostly tested

**Tests Added:**

- `tests/test_rpc_client_methods.py` - Complete test suite for:
  - `get_chain_id()` method with various options
  - `get_code()` method with various options
  - `get_logs()` method with various options
  - `call_contract_function()` method with various options
  - RpcClient properties
  - Chain ID label and operation type passing
  - Error handling through execute_with_retries
- **Remaining**: Lines 407-442, 493 (error handling paths in execute_with_retries, RuntimeError edge case)

**Impact**: Low - Core method implementations are well tested

## Remaining Gaps

### Lower Priority

1. **App Shutdown Edge Cases (`app.py`)** - **88% coverage**

   **Missing Tests:**

   - Shutdown exception handling (lines 226-228, 262-263, 278-280, 289-291, 296-298, 309-311, 320-322, 374-375, 411-412)
   - These are mostly exception handlers in the finally block that catch and ignore errors during shutdown

   **Impact**: Low - These are defensive error handlers that prevent cascading failures during shutdown

1. **RPC Execute With Retries Edge Cases (`rpc.py`)** - **86% coverage**

   **Missing Tests:**

   - Error handling paths in execute_with_retries (lines 407-442)
   - RuntimeError edge case (line 493) - should never happen but good to test

   **Impact**: Low - Core retry logic is well tested, these are edge cases

1. **Main Module Edge Cases (`main.py`)** - **55% coverage**

   **Missing Tests:**

   - `run_servers` error handling (lines 52-58)
   - `if __name__ == "__main__"` block (line 90)

   **Impact**: Low - Core signal handling tested, these are edge cases

1. **Poller Collect Contract Edge Cases (`poller/collect.py`)** - **90% coverage**

   **Missing Tests:**

   - Edge cases in contract collection (lines 242-253, 272-298)

   **Impact**: Low - Core contract collection is well tested

## Recommendations

### Lower Priority

1. **Add tests for app.py shutdown edge cases** - Complete app coverage

   - Test exception handling in shutdown finally blocks (lines 226-228, 262-263, 278-280, 289-291, 296-298, 309-311, 320-322, 374-375, 411-412)
   - These are defensive error handlers that prevent cascading failures during shutdown

1. **Add tests for execute_with_retries edge cases** - Complete RPC coverage

   - Test error handling paths in execute_with_retries (lines 407-442)
   - Test RuntimeError edge case (line 493) - should never happen but good to test

1. **Add tests for main.py edge cases** - Complete main coverage

   - Test `run_servers` error handling (lines 52-58)
   - Test `if __name__ == "__main__"` block (line 90)

1. **Add tests for poller collect contract edge cases** - Complete collect coverage

   - Test edge cases in contract collection (lines 242-253, 272-298)
