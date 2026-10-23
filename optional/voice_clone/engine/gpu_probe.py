"""Check that Chatterbox can actually compute on the local NVIDIA GPU."""
import sys
try:
    import torch
    print('PyTorch:', torch.__version__, 'compiled CUDA:', torch.version.cuda)
    if not torch.cuda.is_available():
        print('CUDA not available to PyTorch. NVIDIA GPU might need correct drivers/wheel.')
        raise SystemExit(2)
    name=torch.cuda.get_device_name(0)
    free,total=torch.cuda.mem_get_info(0)
    x=torch.tensor([2.0, 3.0], device='cuda')
    value=float(torch.sum(x*x).item())
    torch.cuda.synchronize()
    if value != 13.0: raise RuntimeError('GPU compute returned unexpected result')
    print(f'CUDA READY: {name} | free VRAM: {free//(1024*1024)} MB / total: {total//(1024*1024)} MB')
except SystemExit:
    raise
except Exception as e:
    print('CUDA hardware/driver test failed:',type(e).__name__,str(e)[:300])
    raise SystemExit(2)
