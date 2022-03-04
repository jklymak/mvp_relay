# MVP relay

This software reads multiple UDP packets or serial lines, and writes a UDP packets out to a different port.  This allows the Moving Vessel Profiler to just listen to one port.

The software also filters out zeros, which many echo sounders output for bad data.

This is based on relatively complex code, and likely still needs some cleaning.