"""Support for Google KMZ preview generation."""

import shutil
import pathlib
import functools

import numpy as np

from datetime import timedelta
from dateutil import parser

from simplekml import Kml, OverlayXY, ScreenXY, Units, RotationXY

from osgeo import gdal
from osgeo import osr

import matplotlib as mpl
from matplotlib import cm
from matplotlib import pyplot

from .product import Sentinel1Etad


__all__ = ['etad_to_kmz', 'Sentinel1EtadKmlWriter']


class Sentinel1EtadKmlWriter:
    def __init__(self, etad):
        self.etad = etad
        self.etad_file = self.etad.product

        self.kml = Kml()
        self.kml_root = self.kml.newfolder(name=self.etad_file.stem)
        self._set_timespan()

        self.write_overall_footprint()
        self.write_corrections(['sumOfCorrections', 'troposphericCorrection'],
                               decimation_factor=1, colorizing=True)
        self.write_burst_footprint()

    def _set_timespan(self, duration=30, range_=1500000):
        swath = self.etad[list(self.etad.swath_list)[0]]
        burst = swath[list(swath.burst_list)[0]]
        lon0, lat0, lon1, lat1 = burst.get_footprint().bounds
        lat = np.mean([lat0, lat1])
        lon = np.mean([lon0, lon1])
        t0 = parser.parse(self.etad.ds.azimuthTimeMin)
        t1 = t0 + timedelta(seconds=duration)  # configure duration

        self.kml_root.lookat.latitude = lat
        self.kml_root.lookat.longitude = lon
        self.kml_root.lookat.range = range_
        self.kml_root.lookat.gxtimespan.begin = t0.isoformat()
        self.kml_root.lookat.gxtimespan.end = t1.isoformat()

    def save(self, outpath='preview.kmz'):
        outpath = pathlib.Path(outpath)
        assert outpath.suffix.lower() in {'.kml', '.kmz'}
        # dir_ = outpath.with_suffix('')
        dir_ = pathlib.Path('doc')
        dir_.mkdir(exist_ok=True)
        self.kml.save(dir_ / 'doc.kml')

        if outpath.name.lower().endswith('.kmz'):
            shutil.make_archive(str(outpath.with_suffix('')),
                                format='zip', root_dir=str(dir_))
            shutil.move(outpath.with_suffix('.zip'), outpath)
            shutil.rmtree(dir_)

    def write_overall_footprint(self):
        # overall footprints
        data_footprint = self.etad.get_footprint(merge=True)
        x, y = data_footprint.exterior.xy

        corner = [(x[i], y[i]) for i in range(len(x))]

        pol = self.kml_root.newpolygon(name='footprint')
        pol.outerboundaryis = corner
        pol.altitudeMode = 'absolute'
        pol.tessellate = 1
        pol.polystyle.fill = 0
        pol.style.linestyle.width = 2

    def write_burst_footprint(self):
        first_azimuth_time = parser.parse(self.etad.ds.azimuthTimeMin)

        kml_burst_ftp = self.kml_root.newfolder(name='burst_footprint')
        for swath_ in self.etad.swath_list:

            kml_swath_dir = kml_burst_ftp.newfolder(name=swath_)
            etad_swath = self.etad[swath_]
            for bix in etad_swath.burst_list:
                burst_ = etad_swath[bix]

                # get teh footprint and compute the kml gcp list
                ftp_ = burst_.get_footprint()
                x, y = ftp_.exterior.xy
                corner = [(x[i], y[i]) for i in range(len(x))]

                # define the time span
                azimuth_time, _ = burst_.get_burst_grid()
                t0 = first_azimuth_time + timedelta(seconds=azimuth_time[0])
                t1 = first_azimuth_time + timedelta(seconds=azimuth_time[-1])

                # lats, lons, h = burst_.get_lat_lon_heigth()
                pol = kml_swath_dir.newpolygon(name=str(bix))
                pol.outerboundaryis = corner
                pol.altitudeMode = 'absolute'
                pol.tessellate = 1
                pol.polystyle.fill = 0
                pol.style.linestyle.width = 2

                if t1 < t0:
                    t0, t1 = t1, t0
                pol.timespan.begin = t0.isoformat()
                pol.timespan.end = t1.isoformat()

    def write_corrections(self, correction_list, swath_list=None,
                          decimation_factor=1, colorizing=False):
        first_azimuth_time = parser.parse(self.etad.ds.azimuthTimeMin)

        for correction in correction_list:
            # get the parameter list
            prm_list = {}
            xp_ = f".//qualityAndStatistics/{correction}"
            for child in self.etad._annot.find(xp_).getchildren():
                tag = child.tag
                if 'range' in tag:
                    prm_list['x'] = tag
                elif 'azimuth' in tag:
                    prm_list['y'] = tag

            for dim, correction_name in prm_list.items():
                # only enable sum of corrections in range
                # TODO: make configurable
                if correction == 'sumOfCorrections' and dim == 'x':
                    visibility = True
                else:
                    visibility = False

                kml_cor_dir = self.kml_root.newfolder(
                    name=f"{correction}_{prm_list[dim]}")

                cor_max = np.max(
                    self.etad._xpath_to_list(
                        self.etad._annot,
                        f"{xp_}/{prm_list[dim]}/max[@unit='m']", dtype=np.float)
                )
                cor_min = np.min(
                    self.etad._xpath_to_list(
                        self.etad._annot,
                        f"{xp_}/{prm_list[dim]}/min[@unit='m']", dtype=np.float)
                )

                color_table = None
                gdal_palette = None
                if colorizing:
                    color_table = Colorizer(cor_min, cor_max)
                    gdal_palette = color_table.gdal_palette()

                color_table.build_colorbar(f"doc/{correction}_{dim}_cb.png")

                screen = kml_cor_dir.newscreenoverlay(name='ScreenOverlay')
                screen.icon.href = f"{correction}_{dim}_cb.png"
                screen.overlayxy = OverlayXY(x=0, y=0,
                                             xunits=Units.fraction,
                                             yunits=Units.fraction)
                screen.screenxy = ScreenXY(x=0.015, y=0.075,
                                           xunits=Units.fraction,
                                           yunits=Units.fraction)
                screen.rotationXY = RotationXY(x=0.5, y=0.5,
                                               xunits=Units.fraction,
                                               yunits=Units.fraction)

                for swath_ in self.etad.swath_list:
                    kml_swath_dir = kml_cor_dir.newfolder(name=swath_)

                    etad_swath = self.etad[swath_]
                    for bix in etad_swath.burst_list:
                        burst_ = etad_swath[bix]

                        # get teh footprint and compute the kml gcp list
                        ftp_ = burst_.get_footprint()

                        x, y = ftp_.exterior.xy
                        corner = [(x[i], y[i]) for i in range(len(x))]

                        # define the time span
                        azimuth_time, _ = burst_.get_burst_grid()
                        t0 = (first_azimuth_time +
                              timedelta(seconds=azimuth_time[0]))
                        t1 = (first_azimuth_time +
                              timedelta(seconds=azimuth_time[-1]))

                        if correction == 'sumOfCorrections':
                            func_ = functools.partial(
                                burst_.get_correction, name='sum')
                        elif correction == 'troposphericCorrection':
                            func_ = functools.partial(
                                burst_.get_correction, name='tropospheric')
                        else:
                            raise RuntimeError(
                                f'unexpected correction: {correction!r}')

                        etad_correction = func_(meter=True)
                        cor = etad_correction[dim]
                        if colorizing is not None:
                            cor = (cor-cor_min) / np.abs(cor_max-cor_min) * 255
                            pixel_depth = gdal.GDT_Byte
                        else:
                            pixel_depth = gdal.GDT_Float32

                        cor = np.flipud(cor)

                        ground = kml_swath_dir.newgroundoverlay(
                            name='GroundOverlay')
                        ground.visibility = visibility
                        grp = burst_._grp
                        name = f"{grp.pIndex}_{grp.sIndex}_{grp.bIndex}"
                        ground.name = name

                        ground.timespan.begin = t0.isoformat()
                        ground.timespan.end = t1.isoformat()

                        ground.gxlatlonquad.coords = corner

                        # ground.altitudeMode = 'absolute'
                        # ground.polystyle.fill = 0
                        # ground.tessellate=1
                        # ground.style.linestyle.width = 2

                        burst_img = f'burst_{swath_}_{bix}_{correction}_{dim}'
                        ground.icon.href = burst_img + '.tiff'

                        self.array2raster('doc/' + burst_img, cor,
                                          color_table=gdal_palette,
                                          pixel_depth=pixel_depth,
                                          driver='GTiff',
                                          decimation_factor=decimation_factor,
                                          gcp_list=None)

    @staticmethod
    def array2raster(outfile, array, gcp_list=None, color_table=None,
                     pixel_depth=gdal.GDT_Float32, driver='GTiff',
                     decimation_factor=None):
        # http://osgeo-org.1560.x6.nabble.com/Transparent-PNG-with-color-table-palette-td3748906.html
        if decimation_factor is not None:
            array = array[::decimation_factor, ::decimation_factor]

        cols = array.shape[1]
        rows = array.shape[0]

        if driver == 'GTiff':
            outfile += '.tiff'
        elif driver == 'PNG':
            outfile += '.png'
        else:
            raise RuntimeError(f'unexpected driver: {driver}')

        driver = gdal.GetDriverByName(driver)
        outraster = driver.Create(outfile, cols, rows, 1, pixel_depth)

        # outRaster.SetGeoTransform(
        #     (originX, pixelWidth, 0, originY, 0, pixelHeight))
        outband = outraster.GetRasterBand(1)
        if color_table is not None:
            assert(isinstance(color_table, gdal.ColorTable))
            outband.SetRasterColorTable(color_table)
        outband.WriteArray(array)

        out_srs = osr.SpatialReference()
        out_srs.ImportFromEPSG(4326)
        outraster.SetProjection(out_srs.ExportToWkt())

        if gcp_list is not None:
            wkt = outraster.GetProjection()
            outraster.SetGCPs(gcp_list, wkt)

        outband.FlushCache()


# http://osgeo-org.1560.x6.nabble.com/Transparent-PNG-with-color-table-palette-td3748906.html
class Colorizer:
    def __init__(self, vmin, vmax, color_table=cm.viridis):
        # normalize item number values to colormap
        delta = np.abs(vmax - vmin)
        self.vmin = vmin - 0.05*delta
        self.vmax = vmax + 0.05*delta
        self.norm = mpl.colors.Normalize(vmin=self.vmin, vmax=self.vmax)
        self.color_table = color_table

    def rgba_color(self, value):
        # colormap possible values = viridis, jet, spectral
        if self.color_table is None:
            return int(value), int(value), int(value), int(value)
        else:
            return self.color_table(self.norm(value), bytes=True)

    def gdal_palette(self):
        value_list = np.linspace(self.vmin, self.vmax, 255)
        palette = gdal.ColorTable()
        for v in value_list:
            v_ = int((v-self.vmin) / np.abs(self.vmax-self.vmin) * 255)
            palette.SetColorEntry(v_, self.rgba_color(v)[0:3])
        return palette

    def build_colorbar(self, cb_filename):
        # https://ocefpaf.github.io/python4oceanographers/blog/2014/03/10/gearth/
        fig = pyplot.figure(figsize=(0.8, 3))
        ax1 = fig.add_axes([0.1, 0.075, 0.25, 0.85])

        pyplot.tick_params(axis='y', which='major', labelsize=8)

        norm = self.norm

        cb1 = mpl.colorbar.ColorbarBase(ax1, cmap=self.color_table, norm=norm,
                                        orientation='vertical')
        cb1.set_label('[meters]', rotation=90, color='k')
        # This is called from plotpages, in <plotdir>.
        pathlib.Path(cb_filename).parent.mkdir(exist_ok=True)
        pyplot.savefig(cb_filename, transparent=False)


def etad_to_kmz(etad, outpath=None):
    if not isinstance(etad, Sentinel1Etad):
        etad = Sentinel1Etad(etad)

    if outpath is None:
        outpath = etad.product.stem + '.kmz'

    writer = Sentinel1EtadKmlWriter(etad)
    writer.save(outpath)
