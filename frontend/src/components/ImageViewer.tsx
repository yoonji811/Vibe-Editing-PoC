interface Props {
  imageB64: string
  alt?: string
}

export default function ImageViewer({ imageB64, alt = '편집 이미지' }: Props) {
  return (
    <div className="relative w-full flex items-center justify-center bg-gray-100 rounded-2xl overflow-hidden" style={{ height: '100%', maxHeight: '100%' }}>
      <img
        src={`data:image/jpeg;base64,${imageB64}`}
        alt={alt}
        className="max-w-full max-h-full object-contain"
        style={{ maxHeight: '100%' }}
      />
    </div>
  )
}
