import glob
import gzip
import os.path
import re
import warnings

import numpy as np

from .. import config_parser, snapshot, util
from . import DummyHalo, Halo, HaloCatalogue, logger


class AHFCatalogue(HaloCatalogue):

    """
    Class to handle catalogues produced by Amiga Halo Finder (AHF).
    """

    def __init__(self, sim, make_grp=None, get_all_parts=None, use_iord=None, ahf_basename=None,
                 dosort=None, only_stat=None, write_fpos=True, **kwargs):
        """Initialize an AHFCatalogue.

        **kwargs** :

        *make_grp*: if True a 'grp' array is created in the underlying
                    snapshot specifying the lowest level halo that any
                    given particle belongs to. If it is False, no such
                    array is created; if None, the behaviour is
                    determined by the configuration system.

        *get_all_parts*: if True, the particle file is loaded for all halos.
                    Suggested to keep this None, as this is memory intensive.
                    The default function is to load in this data as needed.

        *use_iord*: if True, the particle IDs in the Amiga catalogue
                    are taken to refer to the iord array. If False,
                    they are the particle offsets within the file. If
                    None, the parameter defaults to True for
                    GadgetSnap, False otherwise.

        *ahf_basename*: specify the basename of the AHF halo catalog
                        files - the code will append 'halos',
                        'particles', and 'substructure' to this
                        basename to load the catalog data.

        *dosort*: specify if halo catalog should be sorted so that
                  halo 1 is the most massive halo, halo 2 the
                  second most massive and so on.

        *only_stat*: specify that you only wish to collect the halo
                    properties stored in the AHF_halos file and not
                    worry about particle information

        """

        import os.path
        if not self._can_load(sim, ahf_basename):
            self._run_ahf(sim)

        HaloCatalogue.__init__(self, sim)

        if use_iord is None:
            use_iord = isinstance(
                sim.ancestor,
                (snapshot.gadget.GadgetSnap, snapshot.gadgethdf.GadgetHDFSnap)
            )

        self._use_iord = use_iord

        self._all_parts = get_all_parts
        self._dosort = dosort
        self._only_stat = only_stat

        if ahf_basename is not None:
            self._ahfBasename = ahf_basename
        else:
            candidates = self._list_possible_candidates(sim, ahf_basename)
            if len(candidates) == 1:
                candidate = candidates[0]
            elif len(candidates) == 0:
                raise FileNotFoundError("No candidate AHF catalogue found; try specifying a catalogue using the "
                                        "ahf_basename keyword")
            else:
                candidate = candidates[0]
                warnings.warn(f"Multiple candidate AHF catalogues found; using {candidate}. To specify a different "
                              "catalogue, use the ahf_basename keyword, or move the other catalogues.")
            self._ahfBasename = util.cutgz(candidate)[:-9]

        try:
            with util.open_(self._ahfBasename + 'halos') as f:
                # The first line contains headers, need to skip it
                self._nhalos = sum(1 for i in f) - 1
        except OSError as e:
            raise FileNotFoundError(
                "Halo catalogue not found -- check the base name of catalogue "
                "data or try specifying a catalogue using the ahf_basename "
                "keyword"
            ) from e

        logger.info("AHFCatalogue loading particles")
        self._load_ahf_particles(self._ahfBasename + 'particles')

        logger.info("AHFCatalogue loading halos")
        self._load_ahf_halos(self._ahfBasename + 'halos')

        if self._only_stat is None:
            self._get_file_positions(self._ahfBasename + 'particles')

        if self._dosort is not None:
            nparr = np.array([self._halos[i+1].properties['npart'] for i in range(self._nhalos)])
            osort = np.argsort(nparr)[::-1]
            self._sorted_indices = osort + 1

        self._load_ahf_substructure(self._ahfBasename + 'substructure')

        if make_grp is None:
            make_grp = config_parser.getboolean('AHFCatalogue', 'AutoGrp')

        if make_grp:
            self.make_grp()

        if config_parser.getboolean('AHFCatalogue', 'AutoPid'):
            sim['pid'] = np.arange(0, len(sim))

        if write_fpos:
            if not os.path.exists(self._ahfBasename + 'fpos'):
                self._write_fpos()

        logger.info("AHFCatalogue loaded")

    def __getitem__(self,item):
        """
        get the appropriate halo if dosort is on
        """
        if self._dosort is not None:
            i = self._sorted_indices[item-1]
        else:
            i = item
        return super().__getitem__(i)

    def make_grp(self, name='grp'):
        """
        Creates a 'grp' array which labels each particle according to
        its parent halo.
        """
        self.base[name] = self.get_group_array()

    def _write_fpos(self):
        try:
            with open(self._ahfBasename + 'fpos', 'w') as f:
                for i in range(self._nhalos):
                    if i < self._nhalos - 1:
                        f.write(str(self._halos[i+1].properties['fstart'])+'\n')
                    else:
                        f.write(str(self._halos[i+1].properties['fstart']))
        except OSError:
            warnings.warn("Unable to write AHF_fpos file; performance will be reduced. Pass write_fpos=False to halo constructor to suppress this message.")

    def get_group_array(self, top_level=False, family=None):
        """
        output an array of group IDs for each particle.
        :top_level: If False, each particle associated with the lowest level halo they are in.
                    If True, each particle associated with their top-most level halo
        :family: specify the family of particles to output an array for (default is all particles)
        """

        target = None
        famslice = None

        if family is None:
            target = self.base
        else:
            if family in ['gas','star','dm']:
                famslice = self.base._get_family_slice(family)
                target = self.base[famslice]
            else:
                if family == 'bh':
                    temptarget = self.base.star
                    target = temptarget[(temptarget['tform']<0)]

        if target is None:
            raise ValueError("Family value given is not valid. Use 'gas', 'star', 'dm', or 'bh'")

        if self._dosort is None:
            #if we want to differentiate between top and bottom levels,
            #the halos do need to be in order regardless if dosort is on.
            nparr = np.array([self._halos[i+1].properties['npart'] for i in range(self._nhalos)])
            osort = np.argsort(nparr)[::-1]
            self._sorted_indices = osort + 1
            hcnt = self._sorted_indices

        else:
            hcnt = np.arange(len(self._sorted_indices)) + 1

        if top_level is False:
            hord = self._sorted_indices
        else:
            hord = self._sorted_indices[::-1]
            hcnt = hcnt[::-1]

        if self._all_parts is None:
            f = util.open_(self._ahfBasename+'particles')

        try:
            cnt = 0
            ar = np.full(len(target), -1, dtype=np.int32)

            for i in hord:
                halo = self._halos[i]
                if self._all_parts is not None:
                    ids = halo.get_index_list(self.base)
                else:
                    f.seek(halo.properties['fstart'], 0)
                    ids = self._load_ahf_particle_block(f, halo.properties['npart'])
                if family is None:
                    ar[ids] = hcnt[cnt]
                else:
                    if famslice:
                        t_mask = (ids >= famslice.start) & (ids < famslice.stop)
                        id_t = ids[np.where(t_mask)] - famslice.start
                    else:
                        fpos_ar = target.get_index_list(self.base)
                        id_t, = np.where(np.in1d(fpos_ar, ids))

                    ar[id_t] = hcnt[cnt]
                cnt += 1
        finally:
            if self._all_parts is None:
                f.close()
        return ar

    def _setup_children(self):
        """
        Creates a 'children' array inside each halo's 'properties'
        listing the halo IDs of its children. Used in case the reading
        of substructure data from the AHF-supplied _substructure file
        fails for some reason.
        """

        for i in range(self._nhalos):
            self._halos[i + 1].properties['children'] = []

        for i in range(self._nhalos):
            host = self._halos[i + 1].properties.get('hostHalo', -2)
            if host > -1:
                try:
                    self._halos[host + 1].properties['children'].append(i + 1)
                except KeyError:
                    pass

    def _get_halo(self, i):
        if self.base is None:
            raise RuntimeError("Parent SimSnap has been deleted")
        if self._all_parts is not None:
            return self._halos[i]

        with util.open_(self._ahfBasename+'particles') as f:
            fpos = self._halos[i].properties['fstart']
            f.seek(fpos,0)
            return Halo(
                i,
                self,
                self.base,
                self._load_ahf_particle_block(f, self._halos[i].properties['npart'])
            )



    @property
    def base(self):
        return self._base()

    def load_copy(self, i):
        """Load the a fresh SimSnap with only the particle in halo i"""

        from .. import load

        if self._dosort is not None:
            i = self._sorted_indices[i-1]

        with util.open_(self._ahfBasename + 'particles') as f:
            fpos = self._halos[i].properties['fstart']
            f.seek(fpos,0)
            ids = self._load_ahf_particle_block(f, nparts=self._halos[i].properties['npart'])

        return load(self.base.filename, take=ids)

    def _get_file_positions(self, filename):
        """Get the starting positions of each halo's particle information within the
        AHF_particles file for faster access later"""
        if os.path.exists(self._ahfBasename + 'fpos'):
            with util.open_(self._ahfBasename + 'fpos') as f:
                for i in range(self._nhalos):
                    self._halos[i+1].properties['fstart'] = int(f.readline())
        else:
            with util.open_(filename) as f:
                for h in range(self._nhalos):
                    if len(f.readline().split()) == 1:
                        f.readline()
                    self._halos[h+1].properties['fstart'] = f.tell()
                    for i in range(self._halos[h+1].properties['npart']):
                        f.readline()

    def _load_ahf_particle_block(self, f, nparts=None):
        """Load the particles for the next halo described in particle file f"""
        ng = len(self.base.gas)
        nd = len(self.base.dark)
        ns = len(self.base.star)
        nds = nd+ns

        if nparts is None:
            startline = f.readline()
            if len(startline.split())==1:
                startline = f.readline()
            nparts = int(startline.split()[0])

        if self.isnew:
            if not isinstance(f, gzip.GzipFile):
                data = np.fromfile(
                    f,
                    dtype=int,
                    sep=" ",
                    count=nparts * 2
                ).reshape(nparts, 2)[:, 0]
                data = np.ascontiguousarray(data)
            else:
                # unfortunately with gzipped files there does not
                # seem to be an efficient way to load nparts lines
                data = np.zeros(nparts, dtype=int)
                for i in range(nparts):
                    data[i] = int(f.readline().split()[0])

            if self._use_iord:
                data = self._iord_to_fpos[data]
            elif isinstance(self.base, snapshot.ramses.RamsesSnap):
                # AHF only expects three families, DM, star, gas in this order
                # and generates iords on disc according to this rule
                # For classical Ramses snapshots, this is perfectly adequate, but
                # for more modern outputs that have extra tracers, BHs families
                # we need to offset the ids to return the correct slicing
                # TODO These tests on snapshot type might not be necessary
                #  as using the family logic properly should be general.
                #  It is currently kept to ensure 100% backwards compatibility with previous behaviour,
                #  as this code is not explicitly checked by the pynbody test distribution

                if len(self.base) != nd + ns + ng:                      # We have extra families to the base ones
                    # First identify DM, star and gas particles in AHF
                    ahf_dm_mask = data < nd
                    ahf_star_mask = (data >= nd) & (data < nds)
                    ahf_gas_mask = data >= nds

                    # Then offset them by DM family start, to account for
                    # additional families before it, e.g. gas tracers
                    data[np.where(ahf_dm_mask)] += self.base._get_family_slice('dm').start

                    # Star ids used to start at NDM, now they start with the star family slice
                    offset = self.base._get_family_slice('star').start - nd
                    data[np.where(ahf_star_mask)] += offset

                    # Gas ids were greater than NDM + NSTAR, now they start with the gas slice
                    offset = self.base._get_family_slice('gas').start - nds
                    data[np.where(ahf_gas_mask)] += offset

            elif not isinstance(self.base, snapshot.nchilada.NchiladaSnap):
                hi_mask = data >= nds
                data[np.where(hi_mask)] -= nds
                data[np.where(~hi_mask)] += ng
            else:
                st_mask = (data >= nd) & (data < nds)
                g_mask = data >= nds
                data[np.where(st_mask)] += ng
                data[np.where(g_mask)] -= ns
        else:
            if not isinstance(f, gzip.GzipFile):
                data = np.fromfile(f, dtype=int, sep=" ", count=nparts)
            else:
                # see comment above on gzipped files
                data = np.zeros(nparts, dtype=int)
                for i in range(nparts):
                    data[i] = int(f.readline())
        data.sort()
        return data

    def _load_ahf_particles(self, filename):
        if self._use_iord:
            self._iord_to_fpos = np.zeros(self.base['iord'].max()+1,dtype=int)
            self._iord_to_fpos[self.base['iord']] = np.arange(len(self._base()))

        if filename.split("z")[-2][-1] == ".":
            self.isnew = True
        else:
            self.isnew = False

        if self._all_parts is None:
            for h in range(self._nhalos):
                self._halos[h + 1] = DummyHalo()
            return

        with util.open_(filename) as f:
            for h in range(self._nhalos):
                self._halos[h + 1] = Halo(
                    h + 1, self, self.base, self._load_ahf_particle_block(f))
                self._halos[h + 1]._descriptor = "halo_" + str(h + 1)

    def _load_ahf_halos(self, filename):
        # Note: we need to open in 'rt' mode in case the AHF catalogue
        # is gzipped.
        with util.open_(filename, "rt") as f:
            first_line = f.readline()
            lines = f.readlines()

        # get all the property names from the first, commented line
        # remove (#)
        fields = first_line.replace("#", "").split()
        keys = [re.sub(r'\([0-9]*\)', '', field)
                for field in fields]
        # provide translations
        for i, key in enumerate(keys):
            if self.isnew:
                if(key == '#npart'):
                    keys[i] = 'npart'
            else:
                if(key == '#'):
                    keys[i] = 'dumb'
            if(key == 'a'):
                keys[i] = 'a_axis'
            if(key == 'b'):
                keys[i] = 'b_axis'
            if(key == 'c'):
                keys[i] = 'c_axis'
            if(key == 'Mvir'):
                keys[i] = 'mass'

        if self.isnew:
            # fix for column 0 being a non-column in some versions of the AHF
            # output
            if keys[0] == '#':
                keys = keys[1:]

        for h, line in enumerate(lines):
            values = [
                float(x) if any(_ in x for _ in (".", "e", "nan", "inf"))
                else int(x)
                for x in line.split()
            ]
            # XXX Unit issues!  AHF uses distances in Mpc/h, possibly masses as
            # well
            for i, key in enumerate(keys):
                if self.isnew:
                    self._halos[h + 1].properties[key] = values[i]
                else:
                    self._halos[h + 1].properties[key] = values[i - 1]

    def _load_ahf_substructure(self, filename):
        try:
            with util.open_(filename) as f:
                lines = f.readlines()
        except FileNotFoundError:
            self._setup_children()
            return
        logger.info("AHFCatalogue loading substructure")
        nHalos = int(len(lines)/2) 
        # In the substructure catalog, halos are either referenced by their index
        # or by their ID (if they have one).
        ID2index = {}
        for i, halo in self._halos.items():
            # If the "ID" property doesn't exist, use pynbody's internal index
            id = halo.properties.get("ID", i)
            ID2index[id] = i
  
        for i in range(nHalos):
            try:
                haloid, _nsubhalos = (int(x) for x in lines[2*i].split())
                halo_index = ID2index[haloid]
                children = [
                    ID2index[int(x)] for x in lines[(2*i)+1].split()
                ]
            except ValueError:
                logger.error(
                    "An error occurred while reading substructure file. "
                    "Falling back to using the halo info."
                )
                self._setup_children()
                break
            except KeyError:
                logger.error(
                    (
                        "Could not identify some substructure of "
                        "halo %s. Ignoring"
                    ),
                    haloid + 1
                )
                children = []
            self._halos[halo_index].properties['children'] = children
            for ichild in children:
                self._halos[ichild].properties['parent_id'] = halo_index

    
    def writegrp(self, grpoutfile=False):
        """
        simply write a skid style .grp file from ahf_particles
        file. header = total number of particles, then each line is
        the halo id for each particle (0 means free).
        """
        snapshot = self[1].ancestor
        try:
            snapshot['grp']
        except Exception:
            self.make_grp()
        if not grpoutfile:
            grpoutfile = snapshot.filename + '.grp'
        logger.info("Writing grp file to %s" % grpoutfile)
        with open(grpoutfile, "w") as fpout:
            print(len(snapshot['grp']), file=fpout)

            # writing 1st to a string sacrifices memory for speed.
            # but this is much faster than numpy.savetxt (could make an option).
            # it is assumed that max halo id <= nhalos (i.e.length of string is set
            # len(str(nhalos))
            stringarray = snapshot['grp'].astype(
                '|S' + str(len(str(self._nhalos))))
            outstring = "\n".join(stringarray)
            print(outstring, file=fpout)

    def writestat(self, snapshot, halos, statoutfile, hubble=None):
        """
        write a condensed skid.stat style ascii file from ahf_halos
        file.  header + 1 halo per line. should reproduce `Alyson's
        idl script' except does not do last 2 columns (Is it a
        satellite?) and (Is central halo is `false'ly split?).  output
        units are set to Mpc Msun, km/s.

        user can specify own hubble constant hubble=(H0/(100
        km/s/Mpc)), ignoring the snaphot arg for hubble constant
        (which sometimes has a large roundoff error).
        """
        s = snapshot
        mindarkmass = min(s.dark['mass'])

        if hubble is None:
            hubble = s.properties['h']

        outfile = statoutfile
        logger.info("Writing stat file to %s" % statoutfile)
        with open(outfile, "w") as fout:
            header = "#Grp  N_tot     N_gas      N_star    N_dark    Mvir(M_sol)       Rvir(kpc)       GasMass(M_sol) StarMass(M_sol)  DarkMass(M_sol)  V_max  R@V_max  VelDisp    Xc   Yc   Zc   VXc   VYc   VZc   Contam   Satellite?   False?   ID_A"
            print(header, file=fpout)
            nhalos = halos._nhalos
            for ii in range(nhalos):
                h = halos[ii + 1].properties  # halo index starts with 1 not 0
                # 'Contaminated'? means multiple dark matter particle masses in halo)"
                icontam = np.where(halos[ii + 1].dark['mass'] > mindarkmass)
                if (len(icontam[0]) > 0):
                    contam = "contam"
                else:
                    contam = "clean"
                # may want to add implement satellite test and false central
                # breakup test.

                n_dark = h['npart'] - h['n_gas'] - h['n_star']
                M_dark = h['mass'] - h['M_gas'] - h['M_star']
                ss = "     "  # can adjust column spacing
                outstring = str(int(h['halo_id'])) + ss
                outstring += str(int(h['npart'])) + ss + str(int(h['n_gas'])) + ss
                outstring += str(int(h['n_star'])) + ss + str(int(n_dark)) + ss
                outstring += str(h['mass'] / hubble) + ss + \
                    str(h['Rvir'] / hubble) + ss
                outstring += str(h['M_gas'] / hubble) + ss + \
                    str(h['M_star'] / hubble) + ss
                outstring += str(M_dark / hubble) + ss
                outstring += str(h['Vmax']) + ss + str(h['Rmax'] / hubble) + ss
                outstring += str(h['sigV']) + ss
                # pos: convert kpc/h to mpc (no h).
                outstring += str(h['Xc'] / hubble / 1000.) + ss
                outstring += str(h['Yc'] / hubble / 1000.) + ss
                outstring += str(h['Zc'] / hubble / 1000.) + ss
                outstring += str(h['VXc']) + ss + \
                    str(h['VYc']) + ss + str(h['VZc']) + ss
                outstring += contam + ss
                outstring += "unknown" + \
                    ss  # unknown means sat. test not implemented.
                outstring += "unknown" + ss  # false central breakup.
                print(outstring, file=fpout)

        return 1

    def writetipsy(self, snapshot, halos, tipsyoutfile, hubble=None):
        """
        write halos to tipsy file (write as stars) from ahf_halos
        file.  returns a shapshot where each halo is a star particle.

        user can specify own hubble constant hubble=(H0/(100
        km/s/Mpc)), ignoring the snaphot arg for hubble constant
        (which sometimes has a large roundoff error).
        """
        import math

        from ..analysis import cosmology
        from ..snapshot import new, tipsy
        s = snapshot
        outfile = tipsyoutfile
        nhalos = halos._nhalos
        nstar = nhalos
        sout = new(star=nstar)  # create new tipsy snapshot written as halos.
        sout.properties['a'] = s.properties['a']
        sout.properties['z'] = s.properties['z']
        sout.properties['boxsize'] = s.properties['boxsize']
        if hubble is None:
            hubble = s.properties['h']
        sout.properties['h'] = hubble
    # ! dangerous -- rho_crit function and unit conversions needs simplifying
        rhocrithhco = cosmology.rho_crit(s, z=0, unit="Msol Mpc^-3 h^2")
        lboxkpc = sout.properties['boxsize'].ratio("kpc a")
        lboxkpch = lboxkpc * sout.properties['h']
        lboxmpch = lboxkpc * sout.properties['h'] / 1000.
        tipsyvunitkms = lboxmpch * 100. / (math.pi * 8. / 3.) ** .5
        tipsymunitmsun = rhocrithhco * lboxmpch ** 3 / sout.properties['h']

        for ii in range(nhalos):
            h = halos[ii + 1].properties
            sout.star[ii]['mass'] = h['mass'] / hubble / tipsymunitmsun
            # tipsy units: box centered at 0. (assume 0<=x<=1)
            sout.star[ii]['x'] = h['Xc'] / lboxkpch - 0.5
            sout.star[ii]['y'] = h['Yc'] / lboxkpch - 0.5
            sout.star[ii]['z'] = h['Zc'] / lboxkpch - 0.5
            sout.star[ii]['vx'] = h['VXc'] / tipsyvunitkms
            sout.star[ii]['vy'] = h['VYc'] / tipsyvunitkms
            sout.star[ii]['vz'] = h['VZc'] / tipsyvunitkms
            sout.star[ii]['eps'] = h['Rvir'] / lboxkpch
            sout.star[ii]['metals'] = 0.
            sout.star[ii]['phi'] = 0.
            sout.star[ii]['tform'] = 0.

        sout.write(fmt=tipsy.TipsySnap, filename=outfile)
        return sout

    def writehalos(self, snapshot, halos, hubble=None, outfile=None):
        """ Write the (ahf) halo catalog to disk.  This is really a
        wrapper that calls writegrp, writetipsy, writestat.  Writes
        .amiga.grp file (ascii group ids), .amiga.stat file (ascii
        halo catalog) and .amiga.gtp file (tipsy halo catalog).
        default outfile base simulation is same as snapshot s.
        function returns simsnap of halo catalog.
        """
        s = snapshot
        grpoutfile = s.filename + ".amiga.grp"
        statoutfile = s.filename + ".amiga.stat"
        tipsyoutfile = s.filename + ".amiga.gtp"
        halos.writegrp(grpoutfile)
        halos.writestat(s, halos, statoutfile, hubble=hubble)
        shalos = halos.writetipsy(s, halos, tipsyoutfile, hubble=hubble)
        return shalos

    @staticmethod
    def _list_possible_candidates(sim, ahf_basename):
        if ahf_basename is not None:
            candidates = glob.glob(f"{ahf_basename}*particles*")
        else:
            candidates = set(glob.glob(f"{sim._filename}*z*particles*"))
            # use a set to ensure that no duplicates can be produced
            # This could arise in an edge case where _filename is a directory
            # and having the "/" at the end of it would lead to a first detection here
            # and a second one again below

            if os.path.isdir(sim._filename):
                candidates = candidates.union(glob.glob(os.path.join(sim._filename, "*z*particles*")))

        return list(candidates)

    @classmethod
    def _can_load(cls, sim, ahf_basename=None, **kwargs):
        candidates = cls._list_possible_candidates(sim, ahf_basename)
        number_ahf_file_candidates = len(candidates)
        return number_ahf_file_candidates > 0

    def _run_ahf(self, sim):
        # if (sim is pynbody.tipsy.TipsySnap) :
        typecode = 90
        # elif (sim is pynbody.gadget.GadgetSnap):
        #   typecode = '60' or '61'
        import pynbody.units as units

        # find AHFstep

        groupfinder = config_parser.get('AHFCatalogue', 'Path')

        if groupfinder == 'None':
            for directory in os.environ["PATH"].split(os.pathsep):
                ahfs = glob.glob(os.path.join(directory, "AHF*"))
                for iahf, ahf in enumerate(ahfs):
                    # if there are more AHF*'s than 1, it's not the last one, and
                    # it's AHFstep, then continue, otherwise it's OK.
                    if ((len(ahfs) > 1) & (iahf != len(ahfs) - 1) &
                            (os.path.basename(ahf) == 'AHFstep')):
                        continue
                    else:
                        groupfinder = ahf
                        break

        if not os.path.exists(groupfinder):
            raise RuntimeError("Path to AHF (%s) is invalid" % groupfinder)

        if (os.path.basename(groupfinder) == 'AHFstep'):
            isAHFstep = True
        else:
            isAHFstep = False
        # build units file
        if isAHFstep:
            with open('tipsy.info', 'w') as f:
                f.write(str(sim.properties['omegaM0']) + "\n")
                f.write(str(sim.properties['omegaL0']) + "\n")
                f.write(str(sim['pos'].units.ratio(
                    units.kpc, a=1) / 1000.0 * sim.properties['h']) + "\n")
                f.write(
                    str(sim['vel'].units.ratio(units.km / units.s, a=1)) + "\n")
                f.write(str(sim['mass'].units.ratio(units.Msol)) + "\n")
                f.close()
                # make input file
                f = open('AHF.in', 'w')
                f.write(sim._filename + " " + str(typecode) + " 1\n")
                f.write(sim._filename + "\n256\n5\n5\n0\n0\n0\n0\n")
        else:
            lgmax = np.min([int(2 ** np.floor(np.log2(
                1.0 / np.min(sim['eps'])))), 131072])
            # hardcoded maximum 131072 might not be necessary

            # make input file
            with open('AHF.in', 'w') as f:
                print(config_parser.get('AHFCatalogue', 'Config', vars={
                    'filename': sim._filename,
                    'typecode': typecode,
                    'gridmax': lgmax
                }), file=f)

                print(config_parser.get('AHFCatalogue', 'ConfigTipsy', vars={
                    'omega0': sim.properties['omegaM0'],
                    'lambda0': sim.properties['omegaL0'],
                    'boxsize': sim['pos'].units.ratio('Mpc a h^-1', **sim.conversion_context()),
                    'vunit': sim['vel'].units.ratio('km s^-1 a', **sim.conversion_context()),
                    'munit': sim['mass'].units.ratio('Msol h^-1', **sim.conversion_context()),
                    'eunit': 0.03  # surely this can't be right?
                }), file=f)

        if not os.path.exists(sim._filename):
            os.system("gunzip " + sim._filename + ".gz")
        # determine parallel possibilities

        if os.path.exists(groupfinder):
            # run it
            os.system(groupfinder + " AHF.in")
            return

    @staticmethod
    def _can_run(sim):
        if config_parser.getboolean('AHFCatalogue', 'AutoRun'):
            if config_parser.get('AHFCatalogue', 'Path') == 'None':
                for directory in os.environ["PATH"].split(os.pathsep):
                    if (len(glob.glob(os.path.join(directory, "AHF*"))) > 0):
                        return True
            else:
                path = config_parser.get('AHFCatalogue', 'Path')
                return os.path.exists(path)
        return False
