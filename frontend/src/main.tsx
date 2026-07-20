import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { App } from './App'
import { ToastProvider } from './components/Toast/ToastProvider'
import { queryClient } from './query/client'
import { getAvailableModels } from './api/models'
import './styles/tokens.css'
import './styles/global.css'
import './i18n'

const root = document.getElementById('root')
if (!root) throw new Error('#root element not found in index.html')

void queryClient.prefetchQuery({
  queryKey: ['models', 'available'],
  queryFn: getAvailableModels,
  staleTime: Infinity,
})

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <App />
      </ToastProvider>
    </QueryClientProvider>
  </React.StrictMode>,
)
