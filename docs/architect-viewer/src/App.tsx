import React from 'react'
import ArchitectureDiagram from '../architect'
import DesignDeck from './DesignDeck'

function App() {
  const path = window.location.pathname.replace(/\/$/, '') || '/'

  if (path === '/design') {
    return <DesignDeck />
  }

  return <ArchitectureDiagram />
}

export default App
