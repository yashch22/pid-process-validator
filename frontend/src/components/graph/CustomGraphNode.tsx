import { memo } from 'react';
import { Handle, Position, type NodeProps } from 'reactflow';

interface CustomNodeData {
  id: string;
  type: string;
  label: string;
  icon: string;
  color: string;
  highlighted: boolean;
  attributes: Record<string, string>;
}

function CustomGraphNode({ data, selected }: NodeProps<CustomNodeData>) {
  const isHighlighted = data.highlighted;
  const isSelected = selected;
  const isActive = isHighlighted || isSelected;

  // Strong visual differentiation for highlighted/selected states
  const borderColor = isHighlighted
    ? data.color
    : isSelected
    ? data.color + 'AA'
    : 'hsla(228,12%,18%,0.5)';

  const glowShadow = isHighlighted
    ? `0 0 0 2px ${data.color}30, 0 0 24px ${data.color}25, 0 4px 16px rgba(0,0,0,0.3)`
    : isSelected
    ? `0 0 0 2px ${data.color}20, 0 4px 16px rgba(0,0,0,0.3)`
    : '0 2px 8px rgba(0,0,0,0.2)';

  const bgGradient = isActive
    ? `linear-gradient(135deg, hsla(228,14%,12%,0.95), hsla(228,14%,9%,0.95))`
    : `linear-gradient(135deg, hsla(228,14%,10%,0.85), hsla(228,14%,7%,0.85))`;

  return (
    <div
      className="transition-all duration-300 cursor-pointer select-none"
      style={{
        minWidth: 170,
        background: bgGradient,
        backdropFilter: 'blur(20px)',
        borderRadius: 16,
        border: `1.5px solid ${borderColor}`,
        boxShadow: glowShadow,
        transform: isActive ? 'scale(1.03)' : 'scale(1)',
      }}
    >
      <Handle
        type="target"
        position={Position.Left}
        style={{
          background: data.color,
          width: 10,
          height: 10,
          border: '3px solid hsla(228,14%,8%,0.9)',
          borderRadius: '50%',
          boxShadow: isActive ? `0 0 10px ${data.color}60` : `0 0 6px ${data.color}30`,
        }}
      />
      <div className="px-3.5 py-3 flex items-center gap-3">
        <div
          className="flex h-9 w-9 items-center justify-center text-sm font-bold shrink-0 transition-all duration-300"
          style={{
            backgroundColor: isActive ? data.color + '25' : data.color + '12',
            color: data.color,
            borderRadius: 12,
            boxShadow: isActive ? `0 0 12px ${data.color}20` : `inset 0 0 0 1px ${data.color}15`,
          }}
        >
          {data.icon}
        </div>
        <div className="min-w-0">
          <p className="text-[12px] font-semibold text-foreground leading-tight truncate">{data.label}</p>
          <p className="text-[10px] text-muted-foreground capitalize mt-0.5">{data.type}</p>
        </div>
      </div>
      {Object.keys(data.attributes).length > 0 && (
        <div className="px-3.5 pb-3 pt-0">
          <div className="pt-2 space-y-1" style={{ borderTop: '1px solid hsla(228,12%,16%,0.5)' }}>
            {Object.entries(data.attributes).slice(0, 2).map(([key, value]) => (
              <div key={key} className="flex justify-between gap-2 text-[10px]">
                <span className="text-muted-foreground capitalize truncate">{key.replace('_', ' ')}</span>
                <span className="text-foreground/60 font-mono shrink-0">{value}</span>
              </div>
            ))}
          </div>
        </div>
      )}
      <Handle
        type="source"
        position={Position.Right}
        style={{
          background: data.color,
          width: 10,
          height: 10,
          border: '3px solid hsla(228,14%,8%,0.9)',
          borderRadius: '50%',
          boxShadow: isActive ? `0 0 10px ${data.color}60` : `0 0 6px ${data.color}30`,
        }}
      />
    </div>
  );
}

export default memo(CustomGraphNode);
