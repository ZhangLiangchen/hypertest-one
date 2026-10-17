"use client";

import { Modal } from "antd";
import type { ModalProps } from "antd";
import { useEffect, useState } from "react";

export function ClientModal(props: ModalProps) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted ? <Modal {...props} /> : null;
}
