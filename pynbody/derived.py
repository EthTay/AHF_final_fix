"""
derived
=======

Holds procedures for creating new arrays from existing ones, e.g. for
getting the radial position. For more information see :ref:`derived`.

"""

import functools
import logging
import time
import warnings

import numpy as np

from . import analysis, array, config, units
from .dependencytracker import DependencyError
from .snapshot import SimSnap

logger = logging.getLogger('pynbody.derived')


@SimSnap.derived_quantity
def r(self):
    """Radial position"""
    return ((self['pos'] ** 2).sum(axis=1)) ** (1, 2)


@SimSnap.derived_quantity
def rxy(self):
    """Cylindrical radius in the x-y plane"""
    return ((self['pos'][:, 0:2] ** 2).sum(axis=1)) ** (1, 2)


@SimSnap.derived_quantity
def vr(self):
    """Radial velocity"""
    return (self['pos'] * self['vel']).sum(axis=1) / self['r']


@SimSnap.derived_quantity
def v2(self):
    """Squared velocity"""
    return (self['vel'] ** 2).sum(axis=1)


@SimSnap.derived_quantity
def vt(self):
    """Tangential velocity"""
    return np.sqrt(self['v2'] - self['vr'] ** 2)


@SimSnap.derived_quantity
def ke(self):
    """Specific kinetic energy"""
    return 0.5 * (self['vel'] ** 2).sum(axis=1)


@SimSnap.derived_quantity
def te(self):
    """Specific total energy"""
    return self['ke'] + self['phi']


@SimSnap.derived_quantity
def j(self):
    """Specific angular momentum"""
    angmom = np.cross(self['pos'], self['vel']).view(array.SimArray)
    angmom.units = self['pos'].units * self['vel'].units
    return angmom


@SimSnap.derived_quantity
def j2(self):
    """Square of the specific angular momentum"""
    return (self['j'] ** 2).sum(axis=1)


@SimSnap.derived_quantity
def jz(self):
    """z-component of the angular momentum"""
    return self['j'][:, 2]


@SimSnap.derived_quantity
def vrxy(self):
    """Cylindrical radial velocity in the x-y plane"""
    return (self['pos'][:, 0:2] * self['vel'][:, 0:2]).sum(axis=1) / self['rxy']


@SimSnap.derived_quantity
def vcxy(self):
    """Cylindrical tangential velocity in the x-y plane"""
    f = (self['x'] * self['vy'] - self['y'] * self['vx']) / self['rxy']
    f[np.where(f != f)] = 0
    return f


@SimSnap.derived_quantity
def vphi(self):
    """Azimuthal velocity (synonym for vcxy)"""
    return self['vcxy']


@SimSnap.derived_quantity
def vtheta(self):
    """Velocity projected to polar direction"""
    return (np.cos(self['az']) * np.cos(self['theta']) * self['vx'] +
            np.sin(self['az']) * np.cos(self['theta']) * self['vy'] -
            np.sin(self['theta']) * self['vz'])


_op_dict = {"mean": "mean velocity",
            "disp": "velocity dispersion",
            "curl": "velocity curl",
            "div": "velocity divergence",
            }


def _v_sph_operation(self, op):
    """SPH-smoothed velocity operations"""
    from . import sph

    sph.build_tree(self)

    nsmooth = config['sph']['smooth-particles']

    logger.info('Calculating %s with %d nearest neighbours' % (_op_dict[op], nsmooth))

    if op in ['mean', 'curl']:
        sm = array.SimArray(np.empty_like(self['vel']), self['vel'].units)
    else:
        sm = array.SimArray(np.empty(len(self['vel']), dtype=self['vel'].dtype), self['vel'].units)

    if op in ['div', 'curl']:
        sm.units /= self['pos'].units

    self.kdtree.set_array_ref('rho', self['rho'])
    self.kdtree.set_array_ref('smooth', self['smooth'])
    self.kdtree.set_array_ref('mass', self['mass'])
    self.kdtree.set_array_ref('qty', self['vel'])
    self.kdtree.set_array_ref('qty_sm', sm)

    start = time.time()
    self.kdtree.populate('qty_%s' % op, nsmooth, config['sph']['Kernel'])
    end = time.time()

    logger.info(f'{_op_dict[op]} done in {end - start:5.3g} s')

    return sm


@SimSnap.derived_quantity
def v_mean(self):
    """SPH-smoothed mean velocity"""
    return _v_sph_operation(self, "mean")

@SimSnap.derived_quantity
def v_disp(self):
    """SPH-smoothed velocity dispersion"""
    return _v_sph_operation(self, "disp")

@SimSnap.derived_quantity
def v_curl(self):
    """SPH-smoothed curl of velocity"""
    return _v_sph_operation(self, "curl")

@SimSnap.derived_quantity
def vorticity(self):
    """SPH-smoothed vorticity"""
    return _v_sph_operation(self, "curl")

@SimSnap.derived_quantity
def v_div(self):
    """SPH-smoothed divergence of velocity"""
    return _v_sph_operation(self, "div")

@SimSnap.derived_quantity
def age(self):
    """Stellar age determined from formation time and current snapshot time"""
    return self.properties['time'].in_units(self['tform'].units, **self.conversion_context()) - self['tform']

bands_available = ['u', 'b', 'v', 'r', 'i', 'j', 'h', 'k', 'U', 'B', 'V', 'R', 'I',
                   'J', 'H', 'K']

def lum_den_template(band, s):
        val = (10 ** (-0.4 * s[band + "_mag"])) * s['rho'] / s['mass']
        val.units = s['rho'].units/s['mass'].units
        return val

for band in bands_available:
    X = lambda s, b=str(band): analysis.luminosity.calc_mags(s, band=b)
    X.__name__ = band + "_mag"
    X.__doc__ = band + " magnitude from analysis.luminosity.calc_mags"""
    SimSnap.derived_quantity(X)

    lum_den = functools.partial(lum_den_template,band)

    lum_den.__name__ = band + "_lum_den"
    lum_den.__doc__ = "Luminosity density in astronomy-friendly units: 10^(-0.4 %s_mag) per unit volume. " \
                      "" \
                      "The magnitude is taken from analysis.luminosity.calc_mags."%band
    SimSnap.derived_quantity(lum_den)


@SimSnap.derived_quantity
def theta(self):
    """Angle from the z axis, from [0:pi]"""
    return np.arccos(self['z'] / self['r'])


@SimSnap.derived_quantity
def alt(self):
    """Angle from the horizon, from [-pi/2:pi/2]"""
    return np.pi / 2 - self['theta']


@SimSnap.derived_quantity
def az(self):
    """Angle in the xy plane from the x axis, from [-pi:pi]"""
    return np.arctan2(self['y'], self['x'])


@SimSnap.derived_quantity
def cs(self):
    """Sound speed"""
    return np.sqrt(5.0 / 3.0 * units.k * self['temp'] / self['mu'] / units.m_p)



@SimSnap.derived_quantity
def mu(sim, t0=None, Y=0.245):
    """Mean molecular mass, i.e. the mean atomic mass per particle. Assumes primordial abundances."""
    try:
        x = _mu_from_electron_frac(sim, Y)
    except (KeyError, DependencyError):
        try:
            x = _mu_from_HI_HeI_HeII_HeIII(sim)
        except KeyError:
            x = _mu_from_temperature_threshold(sim, Y, t0)

    x.units = units.Unit("1")
    return x


def _mu_from_temperature_threshold(sim, Y, t0):
    warnings.warn("No ionization fractions found, assuming fully ionised gas above 10^4 and neutral below 10^4K"
                  "This is a very crude approximation.")
    x = np.empty(len(sim)).view(array.SimArray)
    if t0 is None:
        t0 = sim['temp']
    x[np.where(t0 >= 1e4)[0]] = 4. / (8 - 5 * Y)
    x[np.where(t0 < 1e4)[0]] = 4. / (4 - 3 * Y)
    return x


def _mu_from_HI_HeI_HeII_HeIII(sim):
    x = sim["HI"] + 2 * sim["HII"] + sim["HeI"] + \
        2 * sim["HeII"] + 3 * sim["HeIII"]
    x = x ** -1
    return x

def _mu_from_electron_frac(sim, Y):
    return 4./(4.-3.*Y+4*(1.-Y)*sim['ElectronAbundance'])



@SimSnap.derived_quantity
def p(sim):
    """Pressure"""
    p = sim["u"] * sim["rho"] * (2. / 3)
    p.convert_units("Pa")
    return p


@SimSnap.derived_quantity
def u(self):
    """Gas internal energy derived from temperature"""
    gamma = 5. / 3
    return self['temp'] * units.k / (self['mu'] * units.m_p * (gamma - 1))


@SimSnap.derived_quantity
def temp(self):
    """Gas temperature derived from internal energy"""
    gamma = 5. / 3
    mu_est = np.ones(len(self))
    for i in range(5):
        temp = (self['u'] * units.m_p / units.k) * (mu_est * (gamma - 1))
        temp.sim = self # to allow use of conversion context, e.g. scalefactor
        temp.convert_units("K")
        mu_est = mu(self, temp)
    return temp


@SimSnap.derived_quantity
def zeldovich_offset(self):
    """The position offset in the current snapshot according to
    the Zel'dovich approximation applied to the current velocities.
    (Only useful in the generation or analysis of initial conditions.)"""
    from . import analysis
    bdot_by_b = analysis.cosmology.rate_linear_growth(
        self, unit='km Mpc^-1 s^-1') / analysis.cosmology.linear_growth_factor(self)

    a = self.properties['a']

    offset = self['vel'] / (a * bdot_by_b)
    offset.units = self['vel'].units / units.Unit('km Mpc^-1 s^-1 a^-1')
    return offset


@SimSnap.derived_quantity
def aform(self):
    """The expansion factor at the time specified by the tform array."""

    from . import analysis
    z = analysis.cosmology.redshift(self, self['tform'])
    a = 1. / (1. + z)
    return a

@SimSnap.derived_quantity
def tform(self):
    """The time of the specified expansion factor in the aform"""
    from . import analysis
    t = analysis.cosmology.age(self, 1./self['aform'] - 1.)
    return t

@SimSnap.derived_quantity
def iord_argsort(self):
    """Indices so that particles are ordered by increasing ids"""
    return np.argsort(self['iord'])
