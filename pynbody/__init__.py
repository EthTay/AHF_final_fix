"""
pynbody
=======

A light-weight, portable, format-transparent analysis framework
for N-body and SPH astrophysical simulations.

For more information, either build the latest documentation included
in our git repository, or view the online version here:
http://pynbody.github.io/pynbody/

"""

import sys

# We need to import configuration first, so prevent isort from reordering
# isort: off
from .configuration import config, logger, config_parser
# isort: on
from . import (
    analysis,
    array,
    bridge,
    configuration,
    derived,
    family,
    filt,
    gravity,
    halo,
    snapshot,
    sph,
    transformation,
    util,
)
from .snapshot import ascii, gadget, gadgethdf, grafic, nchilada, ramses, tipsy


# The PlotModuleProxy serves to delay import of pynbody.plot until it's accessed.
# Importing pynbody.plot imports pylab which in turn is quite slow and cause problem
# for terminal-only applications. However, since pynbody always auto-imported
# pynbody.plot, it would seem to be too destructive to stop this behaviour.
# So this hack is the compromise and should be completely transparent to most
# users.
class PlotModuleProxy:
    def _do_import(self):
        global plot
        del plot
        from . import plot as plot_module
        plot = plot_module

    def __hasattr__(self, key):
        self._do_import()
        return hasattr(plot, key)

    def __getattr__(self, key):
        self._do_import()
        global plot
        return getattr(plot, key)

    def __setattr__(self, key, value):
        self._do_import()
        global plot
        return setattr(plot, key, value)

    def __dir__(self):
        self._do_import()
        global plot
        return dir(plot)

    def __repr__(self):
        return "<Unloaded plot module>"

plot = PlotModuleProxy()

from .snapshot import load, new

configuration.configure_snapshot_and_halo_loading_priority()

derived_array = snapshot.simsnap.SimSnap.derived_quantity

__version__ = '1.5.2'

__all__ = ['load', 'new', 'derived_array']
