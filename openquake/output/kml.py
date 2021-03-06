# vim: tabstop=4 shiftwidth=4 softtabstop=4

""" KML output class

We're cheating a bit with the xml so that we can write stuff as we get it
rather than generating a giant dom and then writing it to file.

"""

from lxml import etree
from lxml.builder import E

from openquake import writer

KML_HEADER = """
<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Paths</name>
    <description>Examples of paths. Note that the tessellate tag is by default
      set to 0. If you want to create tessellated lines, they must be authored
      (or edited) directly in KML.</description>
    <Style id="yellowLineGreenPoly">
      <LineStyle>
        <color>7f00ffff</color>
        <width>4</width>
      </LineStyle>
      <PolyStyle>
        <color>7f00ff00</color>
      </PolyStyle>
    </Style>
"""

KML_FOOTER = """
  </Document>
</kml>
"""


class KmlFile(writer.FileWriter):
    """Example output class.

    Were this a real class it would probably be doing something much more
    interesting.

    """
    def __init__(self, *args, **kw):
        super(KmlFile, self).__init__(*args, **kw)
        self.file.write(KML_HEADER.strip())

    def write(self, cell, value):
        # cell to kml linestring
        linestring = []
        for x, y in cell.coords:
            linestring.append('%f,%f,2357' % (x, y))

        placemark = (E.Placemark(
                        E.name('foo'),
                        E.description('bar'),
                        E.styleUrl('#yellowLineGreenpoly'),
                        E.LineString(
                            E.extrude('1'),
                            E.tesselate('1'),
                            E.altitudeMode('absolute'),
                            E.coordinates('\n'.join(linestring))
                            )
                        )
                     )

        self.file.write(etree.tostring(placemark, pretty_print=True))

    def close(self):
        self.file.write(KML_FOOTER.strip())
        super(KmlFile, self).close()

