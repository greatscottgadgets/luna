#
# This file is part of LUNA.
#
""" Apollo-based ILA transports. """

from nmigen import Cat

from luna.apollo.support.bits import bits
from luna.gateware.debug.ila  import ILAFrontend


class ApolloILAFrontend(ILAFrontend):
    """ Apollo-based transport for ILA samples. """

    def __init__(self, debugger, *, ila, use_inverted_cs=False):
        """
        Parameters:
            debugger        -- The apollo debugger connection to use for transport.
            ila             -- The ILA object to work with.
            use_inverted_cs -- Use a simple CS multiplexing scheme, where the ILA samples
                               are read out by pulsing SCK while CS is not asserted.
        """
        self._debugger = debugger
        self._use_inverted_cs = use_inverted_cs

        super().__init__(ila)


    def _split_samples(self, all_samples):
        """ Returns an iterator that iterates over each sample in the raw binary of samples. """

        sample_width_bytes = self.ila.bytes_per_sample

        # Iterate over each sample, and yield its value as a bits object.
        for i in range(0, len(all_samples), sample_width_bytes):
            raw_sample    = all_samples[i:i + sample_width_bytes]
            sample_length = len(Cat(self.ila.signals))

            yield bits.from_bytes(raw_sample, length=sample_length, byteorder='big')


    def _read_samples(self):
        """ Reads a set of ILA samples, and returns them. """

        sample_width_bytes = self.ila.bytes_per_sample
        total_to_read      = self.ila.sample_depth * sample_width_bytes

        # Fetch all of our samples from the given device.
        all_samples = self._debugger.spi.transfer(b"\0" * total_to_read)

        return list(self._split_samples(all_samples))


