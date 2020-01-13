#
# This file is part of LUNA.
#
""" Clock domain generation logic for LUNA. """

from abc import ABCMeta, abstractmethod
from nmigen import Signal, Module, ClockDomain, ClockSignal, Elaboratable


class LunaDomainGenerator(Elaboratable, metaclass=ABCMeta):
    """ Helper that generates the clock domains used in a LUNA board.

    Note that this module should create three in-phase clocks; so these domains
    should not require explicit boundary crossings.
    
    I/O port:
        O: clk_fast -- The clock signal for our fast clock domain.
        O: clk_sync -- The clock signal used for our sync clock domain.
        O: clk_ulpi -- The clock signal used for our ulpi domain.
    """

    def __init__(self, *, clock_signal_name=None):
        """
        Parameters:
            clock_signal_name = The clock signal name to use; or None to use the platform's default clock.
        """

        self.clock_name = clock_signal_name

        #
        # I/O port
        #
        self.clk_fast = Signal()
        self.clk_sync = Signal()
        self.clk_ulpi = Signal()


    @abstractmethod
    def generate_fast_clock(self, platform):
        """ Method that returns our platform's fast clock; used for e.g. RAM interfacing. """


    @abstractmethod
    def generate_sync_clock(self, platform):
        """ Method that returns our platform's primary synchronous clock. """


    @abstractmethod
    def generate_ulpi_clock(self, platform):
        """ Method that generates a 60MHz clock used for ULPI interfacing. """



    def elaborate(self, platform):
        m = Module()

        # Create our clock domains.
        m.domains.fast = ClockDomain()
        m.domains.sync = ClockDomain()
        m.domains.ulpi = ClockDomain()

        # Create a clock domain that shifts on the falling edges of the fast clock.
        m.domains.fast_out = ClockDomain()

        # Generate and connect up our clocks.
        m.d.comb += [
            self.clk_sync                  .eq(self.generate_sync_clock(platform)),
            self.clk_fast                  .eq(self.generate_fast_clock(platform)),
            self.clk_ulpi                  .eq(self.generate_ulpi_clock(platform)),

            ClockSignal(domain="fast")     .eq(self.clk_fast),
            ClockSignal(domain="fast_out") .eq(~self.clk_fast),
            ClockSignal(domain="sync")     .eq(self.clk_sync),
            ClockSignal(domain="ulpi")     .eq(self.clk_ulpi),
        ]

        return m


class LunaECP5DomainGenerator(LunaDomainGenerator):

    def generate_sync_clock(self, platform):
        """ Method that returns our platform's primary synchronous clock. """

        # For now, just use our ULPI clock.
        return self.clk_ulpi


    def generate_ulpi_clock(self, platform):
        """ Method that generates a 60MHz clock used for ULPI interfacing. """

        # Use the provided signal name; or the default clock if no name was provided.
        clock_name = self.clock_name if self.clock_name else platform.default_clk
        return platform.request(clock_name)


    def generate_fast_clock(self, platform):
        """ Method that returns our platform's fast clock; used for e.g. RAM interfacing. """

        # For now, just use our ULPI clock.
        return self.clk_ulpi
