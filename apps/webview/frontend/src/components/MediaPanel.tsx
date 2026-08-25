import { Loader, Tabs } from '@mantine/core'
import { useQuery } from '@tanstack/react-query'
import { Disc3, Video, VideoOff } from 'lucide-react'

import { fetchCameras } from '../api/client'
import { CAMERAS_QUERY_KEY, type LiveResponse } from '../api/types'
import { SampleStage } from './SampleStage'

function CamerasPanel() {
  const cameras = useQuery({
    queryKey: CAMERAS_QUERY_KEY,
    queryFn: ({ signal }) => fetchCameras(signal),
    staleTime: 60_000,
  })
  if (cameras.isPending) return <div className="media-empty"><Loader size="sm" /><span>Loading cameras</span></div>
  if (cameras.error) return <div className="media-empty"><VideoOff size={24} /><span>{cameras.error.message}</span></div>
  if (!cameras.data?.items.length) return <div className="media-empty"><VideoOff size={24} /><span>Camera feeds are not configured.</span></div>
  return (
    <div className="camera-list">
      {cameras.data.items.map((camera) => <span key={camera.id}><Video size={16} />{camera.name}</span>)}
    </div>
  )
}

export function MediaPanel({ snapshot }: { snapshot: LiveResponse }) {
  return (
    <section className="panel media-panel" aria-label="Chamber media">
      <Tabs defaultValue="stage" classNames={{ root: 'media-tabs', list: 'media-tab-list', tab: 'media-tab' }}>
        <Tabs.List>
          <Tabs.Tab value="stage" leftSection={<Disc3 size={15} />}>Sample stage</Tabs.Tab>
          <Tabs.Tab value="cameras" leftSection={<Video size={15} />}>Cameras</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="stage"><SampleStage snapshot={snapshot} /></Tabs.Panel>
        <Tabs.Panel value="cameras"><CamerasPanel /></Tabs.Panel>
      </Tabs>
    </section>
  )
}