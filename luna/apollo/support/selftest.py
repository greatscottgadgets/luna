#
# This file is part of LUNA.
#
""" Helpers for building self-test applets around Apollo."""

import sys
import inspect
import logging

from prompt_toolkit import HTML
from prompt_toolkit import print_formatted_text as pprint

from .. import ApolloDebugger


def named_test(name):
    """ Decorator that applies a name to an Apollo test case. """

    # Create a simple decorator that applies the relevant name.
    def decorator(func):
        func.__name__ = name
        return func

    return decorator


class ApolloSelfTestCase:
    """ Self-test running for simple self-tests via Apollo.

    Automatically creates a debugger, and then executes any function with
    a name that starts with `test_`, passing in the debugger connection.
    """

    def fail(self, explanation: str ="called fail()"):
        """ Called to indicate that a test case failed. """
        raise AssertionError(explanation)


    def assertRegisterValue(self, number: int, expected_value: int):
        """ Asserts that a DUT register has a given value. """

        actual_value = self.dut.spi.register_read(number)

        if actual_value != expected_value:
            raise AssertionError(f"register {number} was {actual_value}, not expected {expected_value}")


    def _run_as_test_case(self, method: callable, dut: ApolloDebugger):
        """ Runs a given method as a test case. """

        # Try to run the method...
        try:
            method(dut)

            # If nothing went wrong, succeed.
            result = "<green>✓ PASSED</green>"
            self.successes += 1
        except AssertionError as e:
            result = f"<red>✗ FAILED</red>\t({e})"
            self.failures += 1
        except Exception as e:
            result = f"<red>⚠ EXCEPTION </red>\t({e})"
            self.exceptions += 1

        # ... and print the result.
        name = method.__name__.replace("test_", "")
        pprint(HTML(f"\t{name}:\t{result}"))


    def run_tests(self):
        """ Runs all tests in the given test-case."""

        self.successes  = 0
        self.failures   = 0
        self.exceptions = 0

        # Create our device under test connection.
        dut = self.dut = ApolloDebugger()
        logging.info(f"Connected to onboard debugger; hardware revision r{dut.major}.{dut.minor} (s/n: {dut.serial_number}).")

        # Find all test methods attached to this object...
        logging.info("Running tests...")

        sys.stdout.flush()
        sys.stderr.flush()

        pprint(HTML("\n\n<b><u>Automated tests:</u></b>"))
        for name, member in inspect.getmembers(self):
            if inspect.ismethod(member) and name.startswith('test_'):
                self._run_as_test_case(member, self.dut)

