import { useCallback, useState } from 'react';
import { Upload, FileText, CheckCircle2, Loader2 } from 'lucide-react';
import { motion } from 'framer-motion';
import { Button } from '@/components/ui/button';

interface UploadCardProps {
  title: string;
  description: string;
  accept: string;
  onFileSelect: (file: File) => void;
  isUploading?: boolean;
  isComplete?: boolean;
  completedLabel?: string;
  icon?: React.ReactNode;
}

export default function UploadCard({ title, description, accept, onFileSelect, isUploading, isComplete, completedLabel, icon }: UploadCardProps) {
  const [dragOver, setDragOver] = useState(false);
  const [fileName, setFileName] = useState<string | null>(null);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) { setFileName(file.name); onFileSelect(file); }
  }, [onFileSelect]);

  const handleChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) { setFileName(file.name); onFileSelect(file); }
  }, [onFileSelect]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
      className="glass rounded-2xl gradient-border overflow-hidden group hover:glow-sm transition-all duration-500"
    >
      <div className="p-5">
        <div className="flex items-center gap-2.5 mb-4">
          {icon && <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-primary/10 text-primary">{icon}</div>}
          <h3 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">{title}</h3>
        </div>
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={`relative flex flex-col items-center justify-center rounded-xl border-2 border-dashed p-8 transition-all duration-300 ${
            isComplete
              ? 'border-success/30 bg-success/[0.04]'
              : dragOver
              ? 'border-primary/50 bg-primary/[0.06]'
              : 'border-white/[0.06] hover:border-white/[0.12] hover:bg-white/[0.02]'
          }`}
        >
          {isComplete ? (
            <motion.div initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} className="flex flex-col items-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-success/10 mb-3">
                <CheckCircle2 className="h-6 w-6 text-success" />
              </div>
              <p className="text-sm font-semibold text-success">{completedLabel || 'Upload complete'}</p>
              <p className="text-[11px] text-muted-foreground mt-1 font-mono">{fileName}</p>
            </motion.div>
          ) : (
            <>
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-white/[0.04] mb-3 group-hover:bg-primary/10 transition-colors duration-300">
                <Upload className="h-5 w-5 text-muted-foreground group-hover:text-primary transition-colors duration-300" />
              </div>
              <p className="text-sm text-foreground/80 font-medium mb-0.5">{description}</p>
              <p className="text-[11px] text-muted-foreground/60 mb-4">Drag & drop or click to browse</p>
              <Button variant="outline" size="sm" asChild disabled={isUploading} className="h-8 text-xs rounded-lg border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06]">
                <label className="cursor-pointer gap-1.5">
                  {isUploading ? <Loader2 className="h-3 w-3 animate-spin" /> : <FileText className="h-3 w-3" />}
                  {isUploading ? 'Uploading...' : 'Select File'}
                  <input type="file" accept={accept} className="hidden" onChange={handleChange} />
                </label>
              </Button>
            </>
          )}
        </div>
      </div>
    </motion.div>
  );
}
