import { useState, useEffect, useRef } from 'react'
import type { SystemData, NetworkSample, DiskSample, ProcessInfo } from '../types.d'

const MAX_HISTORY = 60

const initial: SystemData = {
  cpuLoad: 0,
  cpuHistory: [],
  cpuTemp: 0,
  cpuCores: 4,
  ramUsed: 0,
  ramTotal: 8,
  ramPercent: 0,
  netHistory: [],
  netInterface: 'eth0',
  diskHistory: [],
  diskUsed: 0,
  diskTotal: 0,
  processes: [],
  uptimeSecs: 0,
}

function push<T>(arr: T[], item: T): T[] {
  return [...arr, item].slice(-MAX_HISTORY)
}

export function useSystemData(): SystemData {
  const [data, setData] = useState<SystemData>(initial)
  const hist = useRef({
    cpu: [] as number[],
    net: [] as NetworkSample[],
    disk: [] as DiskSample[],
  })

  useEffect(() => {
    const api = window.electronAPI
    if (!api) return

    api.onSystemData((raw: unknown) => {
      const r = raw as Record<string, unknown>

      const load = r.load as Record<string, unknown> | undefined
      const mem  = r.mem  as Record<string, number>  | undefined
      const netArr = r.net as Record<string, number>[] | undefined
      const disk = r.disk as Record<string, number>  | undefined
      const procs = r.procs as { list: Record<string, unknown>[] } | undefined
      const temp  = r.temp as Record<string, number>  | undefined
      const fsArr = r.fs   as Record<string, number>[] | undefined

      // CPU
      const cpuLoad = (load?.currentLoad as number) ?? 0
      hist.current.cpu = push(hist.current.cpu, cpuLoad)

      // Network — first active interface
      const netIface = netArr?.[0]
      const rx = ((netIface?.rx_sec as number) ?? 0) / 1e6
      const tx = ((netIface?.tx_sec as number) ?? 0) / 1e6
      hist.current.net = push(hist.current.net, { rx, tx })

      // Disk I/O
      const rIO = ((disk?.rIO_sec as number) ?? 0) / 1e6
      const wIO = ((disk?.wIO_sec as number) ?? 0) / 1e6
      hist.current.disk = push(hist.current.disk, { r: rIO, w: wIO })

      // RAM
      const ramTotal = ((mem?.total as number) ?? 0) / 1e9
      const ramUsed  = ((mem?.used  as number) ?? 0) / 1e9
      const ramPercent = ramTotal > 0 ? (ramUsed / ramTotal) * 100 : 0

      // Filesystem (root partition)
      const rootFs = fsArr?.find(f => (f.mount as string) === '/') ?? fsArr?.[0]
      const diskTotal = ((rootFs?.size   as number) ?? 0) / 1e9
      const diskUsed  = ((rootFs?.used   as number) ?? 0) / 1e9

      // Processes
      const rawList = (procs?.list ?? []) as Record<string, unknown>[]
      const processes: ProcessInfo[] = rawList
        .map(p => ({
          pid:    (p.pid    as number)  ?? 0,
          name:   (p.name   as string)  ?? '',
          cpu:    (p.cpu    as number)  ?? 0,
          memRss: Math.round(((p.memRss as number) ?? 0) / 1024 / 1024),
          state:  (p.state  as string)  ?? 'unknown',
        }))
        .filter(p => p.name)
        .sort((a, b) => b.cpu - a.cpu)
        .slice(0, 60)

      setData({
        cpuLoad,
        cpuHistory: [...hist.current.cpu],
        cpuTemp:   (temp?.main as number) ?? 0,
        cpuCores:  (load?.cpus as unknown[])?.length ?? 4,
        ramUsed,
        ramTotal,
        ramPercent,
        netHistory: [...hist.current.net],
        netInterface: (netIface?.iface as string) ?? 'eth0',
        diskHistory: [...hist.current.disk],
        diskUsed,
        diskTotal,
        processes,
        uptimeSecs: (r.uptimeSecs as number) ?? 0,
      })
    })

    return () => {
      api.removeSystemDataListener()
    }
  }, [])

  return data
}
