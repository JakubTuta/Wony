// The map's first screen: nothing is drawn until there is a picture, so this
// says what the map is for, what to do, and takes the picture.
import { useState } from 'react';
import { ImagePlus, Loader2 } from 'lucide-react';
import type { DeviceMap } from '../../api';
import { CARD } from '../../components/ui';
import { IMAGE_TYPES, useMapUpload } from './mapUpload';

const STEPS = [
  'Upload a floor plan, or a photo of your home.',
  'Drag your devices onto it.',
  'Tap a device on the map to switch it on or off.',
];

export function MapStart({ onUploaded }: { onUploaded: (map: DeviceMap) => void }) {
  const { upload, uploading, error } = useMapUpload(onUploaded);
  const [over, setOver] = useState(false);

  return (
    <div className={`${CARD} p-8 flex flex-col items-center gap-6 text-center`}>
      <div className="flex flex-col gap-1.5">
        <h2 className="m-0 text-xl font-bold">Put your home on a map</h2>
        <span className="text-sm text-muted">
          See every device where it really is, and switch it with one tap.
        </span>
      </div>

      <ol className="m-0 p-0 list-none flex gap-x-8 gap-y-3 flex-wrap justify-center text-left">
        {STEPS.map((step, i) => (
          <li key={step} className="flex items-center gap-2.5 max-w-[230px]">
            <span className="w-6 h-6 shrink-0 rounded-full bg-teal-soft text-teal text-xs font-bold flex items-center justify-center">
              {i + 1}
            </span>
            <span className="text-sm">{step}</span>
          </li>
        ))}
      </ol>

      <label
        className="w-full max-w-[520px] rounded-[14px] border-2 border-dashed px-6 py-9 flex flex-col items-center gap-2 cursor-pointer focus-within:outline-2"
        style={{
          borderColor: over ? 'var(--color-teal)' : 'var(--color-dashed-border)',
          background: over ? 'var(--color-teal-soft)' : 'var(--color-page)',
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          upload(e.dataTransfer.files[0]);
        }}
      >
        <input
          type="file"
          accept={IMAGE_TYPES}
          className="sr-only"
          disabled={uploading}
          onChange={(e) => {
            upload(e.target.files?.[0]);
            e.target.value = '';
          }}
        />
        {uploading ? (
          <Loader2 size={28} className="animate-spin text-teal" />
        ) : (
          <ImagePlus size={28} className="text-teal" />
        )}
        <span className="text-sm font-semibold">
          {uploading ? 'Uploading…' : 'Drop an image here, or click to choose one'}
        </span>
        <span className="text-xs text-muted">
          PNG, JPG or WebP, up to 15 MB. A screenshot of a floor plan or a photo of a sketch works well.
        </span>
      </label>

      {error && <span className="text-sm text-red">{error}</span>}
    </div>
  );
}
