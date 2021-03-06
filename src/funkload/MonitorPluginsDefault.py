# (C) 2011 Nuxeo SAS <http://nuxeo.com>
# Authors: Krzysztof A. Adamski
#          bdelbosc@nuxeo.com
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
import psutil
from  MonitorPlugins import MonitorPlugin, Plot

class MonitorCUs(MonitorPlugin):
    plot1 = [('CUs', 'impulse', 'CUs')]
    plots = [Plot(plot1, title="Concurent users", ylabel="CUs")]

    def getStat(self):
        return {}

    def parseStats(self, stats):
        if not (hasattr(stats[0], 'cvus')):
            return None
        cus = [int(x.cvus) for x in stats]

        return {'CUs': cus}

class MonitorMemFree(MonitorPlugin):
    plot1 = [('MEM', 'lines lw 2', 'Memory'),
             ('SWAP', 'lines lw 2', 'Swap')]
    plots = [Plot(plot1, title="Memory usage delta", unit="bytes")]

    def getStat(self):
        return {'memTotal': psutil.TOTAL_PHYMEM,
                'memFree': psutil.avail_phymem(),
                'swapTotal': psutil.total_virtmem(),
                'swapFree': psutil.avail_virtmem(),
                'buffers': psutil.phymem_buffers(),
                'cached': psutil.cached_phymem()}


    def parseStats(self, stats):
        if not (hasattr(stats[0], 'memTotal') and
                hasattr(stats[0], 'memFree') and
                hasattr(stats[0], 'swapTotal') and
                hasattr(stats[0], 'swapFree')):
            return None
        mem_total = int(stats[0].memTotal)
        if hasattr(stats[0], 'buffers'):
            mem_used = [mem_total - int(x.memFree) - int(x.buffers) - int(x.cached) for x in stats]
        else:
            # old monitoring does not have cached or buffers info
            mem_used = [mem_total - int(x.memFree) for x in stats]           
        mem_used_start = mem_used[0]
        mem_used = [x - mem_used_start for x in mem_used]
        swap_total = int(stats[0].swapTotal)
        swap_used = [swap_total - int(x.swapFree) for x in stats]
        swap_used_start = swap_used[0]
        swap_used = [x - swap_used_start for x in swap_used]
        return {'MEM': mem_used, 'SWAP': swap_used}

class MonitorCPU(MonitorPlugin):
    plot1 = [('CPU', 'impulse lw 2', 'CPU 1=100%'),
             ('LOAD1', 'lines lw 2','Load 1min'),
             ('LOAD5', 'lines lw 2', 'Load 5min'),
             ('LOAD15', 'lines lw 2', 'Load 15min')]
    plots = [Plot(plot1, title="Load average", ylabel="loadavg")]

    def getStat(self):
        return dict(self._getCPU().items() + self._getLoad().items())

    def _getCPU(self):
        """Read the current system cpu usage from /proc/stat."""
        cputime = psutil.cpu_times()

        total_jiffies = cputime.system + cputime.idle + cputime.user
        idle_jiffies = cputime.idle

        return {'CPUTotalJiffies': total_jiffies,
                'IDLTotalJiffies': idle_jiffies}


    def _getLoad(self):
        """Read the current system load from /proc/loadavg."""
        loadavg = open("/proc/loadavg").readline().strip()
        # Contents are space separate
        # <load1> <load5> <load15> <running process>, <total threads>, <last pid>
        stats = loadavg.split()
        running = stats[3].split("/")
        load_stats = {}
        load_stats['loadAvg1min'] = stats[0]
        load_stats['loadAvg5min'] = stats[1]
        load_stats['loadAvg15min'] = stats[2]
        load_stats['running'] = running[0]
        load_stats['tasks'] = running[1]
        return load_stats

    def parseStats(self, stats):
        if not (hasattr(stats[0], 'loadAvg1min') and
                hasattr(stats[0], 'loadAvg5min') and
                hasattr(stats[0], 'loadAvg15min')):
            return None
        cpu_usage = [0]
        for i in range(1, len(stats)):
            if not (hasattr(stats[i], 'CPUTotalJiffies') and
                    hasattr(stats[i-1], 'CPUTotalJiffies')):
                cpu_usage.append(None)
            else:
                dt_idl = float(stats[i].IDLTotalJiffies) - float(stats[i-1].IDLTotalJiffies)
                dt_cpu = float(stats[i].CPUTotalJiffies) - float(stats[i-1].CPUTotalJiffies)
                dt = dt_idl + dt_cpu
                if dt:
                    ttl = dt_cpu / dt
                else:
                    ttl = None
                cpu_usage.append(ttl)

        load_avg_1 = [float(x.loadAvg1min) for x in stats]
        load_avg_5 = [float(x.loadAvg5min) for x in stats]
        load_avg_15 = [float(x.loadAvg15min) for x in stats]
        return {'LOAD1': load_avg_1, 
                'LOAD5': load_avg_5, 
                'LOAD15': load_avg_15,
                'CPU': cpu_usage}


class MonitorNetwork(MonitorPlugin):
    interface='eth0'
    plot1=[('NETIN', 'lines lw 2', 'In'),
           ('NETOUT', 'lines lw 2','Out')]
    plots=[Plot(plot1, title="Network traffic", ylabel="", unit = "kB")]

    def __init__(self, conf):
        super(MonitorNetwork, self).__init__(conf)
        if conf!=None:
            self.interface = conf.get('server', 'interface')

    def getStat(self):
        """Read the stats from an interface."""
        ifaces = open("/proc/net/dev")
        # Skip the information banner
        ifaces.readline()
        ifaces.readline()
        # Read the rest of the lines
        lines = ifaces.readlines()
        ifaces.close()
        for line in lines:
            # Parse the interface line
            # Interface is followed by a ':' and then bytes, possibly with
            # no spaces between : and bytes
            line = line.strip()
            (device, sep, data) = line.partition(':')

            # Get rid of leading spaces
            device = device.lstrip()

            if device != self.interface:
                continue

            stats = data.split()
            return {'receiveBytes': stats[0],
                    'receivePackets': stats[1],
                    'transmitBytes': stats[8],
                    'transmitPackets': stats[9]}
        return {}

    def parseStats(self, stats):
        if not (hasattr(stats[0], 'transmitBytes') or
                hasattr(stats[0], 'receiveBytes')):
            return None
        net_in = [None]
        net_out = [None]
        for i in range(1, len(stats)):
            if not (hasattr(stats[i], 'receiveBytes') and
                    hasattr(stats[i-1], 'receiveBytes')):
                net_in.append(None)
            else:
                net_in.append((int(stats[i].receiveBytes) -
                               int(stats[i-1].receiveBytes)) /
                              (1024 * (float(stats[i].time) -
                                       float(stats[i-1].time))))

            if not (hasattr(stats[i], 'transmitBytes') and
                    hasattr(stats[i-1], 'transmitBytes')):
                net_out.append(None)
            else:
                net_out.append((int(stats[i].transmitBytes) -
                                int(stats[i-1].transmitBytes))/
                              (1024 * (float(stats[i].time) -
                                       float(stats[i-1].time))))
        return {'NETIN': net_in, 'NETOUT': net_out}

