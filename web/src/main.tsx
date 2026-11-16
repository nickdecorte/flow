import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from '@/App'
import { TooltipProvider } from '@/components/ui/tooltip'
import '@/index.css'

// shadcn themes on a `.dark` class; the old page followed the system theme, so the class does too.
const dark = window.matchMedia('(prefers-color-scheme: dark)')
const applyTheme = () => document.documentElement.classList.toggle('dark', dark.matches)
applyTheme()
dark.addEventListener('change', applyTheme)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <TooltipProvider>
      <App />
    </TooltipProvider>
  </StrictMode>,
)
