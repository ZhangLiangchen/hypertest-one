"use client";

import type { ModalProps } from "antd";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

const Modal = dynamic(() => import("antd/es/modal").then((module) => module.default));

export function ClientModal(props: ModalProps) {
  const [mounted, setMounted] = useState(false);
  const [opened, setOpened] = useState(false);
  useEffect(() => setMounted(true), []);
  useEffect(() => { if (props.open) setOpened(true); }, [props.open]);
  // Defer the first mount, then keep the same form and draft on close/reopen.
  return mounted && (props.open || opened) ? <Modal {...props} /> : null;
}
