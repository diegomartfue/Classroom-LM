import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ArrowLeft, Upload, CheckCircle, Loader2, AlertCircle } from 'lucide-react';


interface UploadMaterialsProps {
  onViewChange: (view: string) => void;
}

export function UploadMaterials({ onViewChange }: UploadMaterialsProps) {
  const [file, setFile] = useState<File | null>(null);
  const [status, setStatus] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle');
  const [message, setMessage] = useState('');

  const handleUpload = async () => {
    if (!file) return;

    const formData = new FormData();
    formData.append('file', file);

    setStatus('uploading');

    try {
      const response = await fetch('http://localhost:8000/upload', {
        method: 'POST',
        body: formData,
      });

      const data = await response.json();

      if (data.status === 'success') {
        setStatus('success');
        setMessage(`Successfully stored ${data.chunks_stored} chunks from "${file.name}"`);
      } else {
        setStatus('error');
        setMessage(data.message || 'Upload failed');
      }
    } catch (err) {
      setStatus('error');
      setMessage('Could not connect to backend. Is it running?');
    }
  };

  return (
    <div className="p-8 max-w-2xl mx-auto space-y-6 animate-in fade-in duration-500">
      {/* Header */}
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="icon" onClick={() => onViewChange('dashboard')}>
          <ArrowLeft className="w-5 h-5" />
        </Button>
        <div>
          <h1 className="text-2xl font-bold text-slate-800">Upload Course Materials</h1>
          <p className="text-slate-500">Upload a PDF to make it available to the AI tutor</p>
        </div>
      </div>

      {/* Upload Card */}
      <Card className="border-0 shadow-lg">
        <CardHeader>
          <CardTitle className="text-lg">Select a PDF</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <input
            type="file"
            accept=".pdf"
            onChange={(e) => {
              setFile(e.target.files?.[0] || null);
              setStatus('idle');
              setMessage('');
            }}
            className="w-full text-sm text-slate-500 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
          />

          {file && (
            <p className="text-sm text-slate-600">
              Selected: <span className="font-medium">{file.name}</span>
            </p>
          )}

          <Button
            className="w-full gap-2 bg-indigo-600 hover:bg-indigo-700 h-12"
            onClick={handleUpload}
            disabled={!file || status === 'uploading'}
          >
            {status === 'uploading' ? (
              <>
                <Loader2 className="w-5 h-5 animate-spin" />
                Uploading...
              </>
            ) : (
              <>
                <Upload className="w-5 h-5" />
                Upload PDF
              </>
            )}
          </Button>

          {/* Status Messages */}
          {status === 'success' && (
            <div className="flex items-center gap-2 p-4 bg-teal-50 rounded-xl border border-teal-200">
              <CheckCircle className="w-5 h-5 text-teal-600 flex-shrink-0" />
              <p className="text-sm text-teal-700">{message}</p>
            </div>
          )}

          {status === 'error' && (
            <div className="flex items-center gap-2 p-4 bg-red-50 rounded-xl border border-red-200">
              <AlertCircle className="w-5 h-5 text-red-600 flex-shrink-0" />
              <p className="text-sm text-red-700">{message}</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}