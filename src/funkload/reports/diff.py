# (C) Copyright 2008 Nuxeo SAS <http://nuxeo.com>
# Author: bdelbosc@nuxeo.com
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as published
# by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA
# 02111-1307, USA.
#
"""Classes that render a differential report

$Id$
"""
import os
from funkload.utils import render_template
import hashlib
from funkload.gnuplot import gnuplot, gnuplot_scriptpath, strictly_monotonic
from shutil import copyfile
from funkload.reports.extraction import extract_report_data

def getReadableDiffReportName(a, b):
    """Return a readeable diff report name using 2 reports"""
    a = os.path.basename(a)
    b = os.path.basename(b)
    if a == b:
        return "diff_" + a + "_vs_idem"
    for i in range(min(len(a), len(b))):
        if a[i] != b[i]:
            break
    for i in range(i, 0, -1):
        # try to keep numbers
        if a[i] not in "_-0123456789":
            i += 1
            break

    r = b[:i] + "_" + b[i:] + "_vs_" + a[i:]
    if r.startswith('test_'):
        r = r[5:]
    r = r.replace('-_', '_')
    r = r.replace('_-', '_')
    r = r.replace('__', '_')
    return "diff_" + r


class DiffReport(object):
    """
    Create a report comparing two funkload runs

    `report_dir1`:
        The path to the first report to compare

    `report_dir2`:
        The path to the second report to compare
    """
    def __init__(self, report_dir1, report_dir2):
        # Swap windows path separator backslashes for forward slashes
        # Windows accepts '/' but some file formats like rest treat the
        # backslash specially.
        self.report1 = os.path.abspath(os.path.join(report_dir1, 'index.rst')).replace('\\', '/')
        self.report2 = os.path.abspath(os.path.join(report_dir2, 'index.rst')).replace('\\', '/')
        self.header = None
        self.data1 = extract_report_data(self.report1)
        self.data2 = extract_report_data(self.report2)
        self.comparable_keys = set(self.data1.keys()) & set(self.data2.keys())
    
    def generate_report_dir_name(self):
        """Generate a directory name for a report."""
        return getReadableDiffReportName(
            os.path.dirname(self.report1),
            os.path.dirname(self.report2)
        )

    def store_data_files(self, report_dir):
        """
        Copy the data required for this report to the report_dir
        """
        copyfile(self.report1, os.path.join(report_dir, 'left.rst'))
        copyfile(self.report2, os.path.join(report_dir, 'right.rst'))

    def render(self, output_format, image_paths={}):
        """
        Create the report in the specified output format

        `output_format`:
            The output format of the report (currently, can be rst or org)

        `image_paths`: dict
            A dictionary mapping image keys to their paths on disk
        """
        return render_template(
            '{output_format}/diff.mako'.format(output_format=output_format),
            left_path=self.report1,
            left_name=os.path.basename(os.path.dirname(self.report1)),
            right_path=self.report2,
            right_name=os.path.basename(os.path.dirname(self.report2)),
            comparable_keys=self.comparable_keys,
            left_keys=set(self.data1.keys()),
            right_keys=set(self.data2.keys()),
            image_paths=image_paths,
        )

    def render_charts(self, report_dir):
        """Render stats."""
        images = {}
        for key in sorted(self.comparable_keys):
            per_second, response_times = self.create_diff_chart(key, report_dir)
            images[(key, 'per_second')] = per_second
            images[(key, 'response_times')] = response_times
        return images

    def create_diff_chart(self, key, report_dir):
        """
        Generate the diff chart for the specified key, comparing the
        two reports for this diff.

        `key`:
            A section key that appears in both reports

        `report_dir`:
            The directory to write the data, gnuplot, and image files
        """
        output_name = 'diff_{hash}'.format(hash=hashlib.md5(str(key)).hexdigest())
        per_second_name = output_name + '.per_second.png'
        response_times_name = output_name + '.response.png'
        per_second_path = gnuplot_scriptpath(report_dir, per_second_name)
        response_times_path = gnuplot_scriptpath(report_dir, response_times_name)
        gplot_path = str(os.path.join(report_dir, output_name + '.gplot'))
        data_path = gnuplot_scriptpath(report_dir, output_name + '.data')

        labels = []
        data = []

        left_data = self.data1[key]
        right_data = self.data2[key]

        columns = set(left_data.keys()) & set(right_data.keys())
        cycles = [int(v) for v in left_data['CUs']]

        for column_name in columns:
            labels.extend(['L_' + column_name, 'R_' + column_name])

        for idx in range(len(cycles)):
            values = []
            for column_name in columns:
                values.append(left_data[column_name][idx])
                values.append(right_data[column_name][idx])
            data.append(values)

        with open(data_path, 'w') as data_file:
            data_file.write(render_template(
                'gnuplot/data.mako',
                labels=labels,
                data=data
            ))

        with open(gplot_path, 'w') as gplot_file:
            gplot_file.write(render_template(
                'gnuplot/diff.mako',
                per_second_path=per_second_path,
                response_times_path=response_times_path,
                use_xticlabels=not strictly_monotonic(cycles),
                left_path=self.report1,
                right_path=self.report2,
                data_path=data_path,
                key=key,
                column_names=labels,
            ))
        gnuplot(gplot_path)

        return (per_second_name, response_times_name)
