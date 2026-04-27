import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { App } from './App'
import { queryClient } from './query/client'
import './styles/tokens.css'
import './styles/global.css'
import './i18n'

const root = document.getElementById('root')
if (!root) throw new Error('#root element not found in index.html')

ReactDOM.createRoot(root).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </React.StrictMode>,
)
