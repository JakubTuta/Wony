import { useState } from 'react';
import { uploadMapImage } from '../../api';
import type { DeviceMap } from '../../api';

// Mirrors helpers/home_map.py, which is the one that enforces it.
const MAX_BYTES = 15 * 1024 * 1024;
export const IMAGE_TYPES = 'image/png,image/jpeg,image/webp';

/** Sending a picture as the map, whether it is the first one or a replacement. */
export function useMapUpload(onUploaded: (map: DeviceMap) => void) {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const upload = async (file: File | undefined) => {
    if (!file) return;
    if (file.size > MAX_BYTES) {
      setError('That file is too big. The limit is 15 MB.');
      return;
    }
    setUploading(true);
    setError(null);
    const result = await uploadMapImage(file);
    setUploading(false);
    if (result.ok) onUploaded(result.data);
    else setError(result.text);
  };

  return { upload, uploading, error };
}
