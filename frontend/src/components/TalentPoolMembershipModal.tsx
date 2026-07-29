import { DatabaseOutlined } from '@ant-design/icons'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Alert, Form, Input, Modal, Select, Typography } from 'antd'
import { useState } from 'react'

import {
  ApiError,
  addTalentPoolMemberships,
  fetchTalentPoolGroups,
  type TalentPoolMembershipOperationRecord,
} from '../api/client'

const { Text } = Typography

interface MembershipFormValues {
  groupId: string
  reason: string
}

export function TalentPoolMembershipModal({
  open,
  candidateIds,
  onClose,
  onSuccess,
}: {
  open: boolean
  candidateIds: string[]
  onClose: () => void
  onSuccess: (result: TalentPoolMembershipOperationRecord) => void
}) {
  const [form] = Form.useForm<MembershipFormValues>()
  const [error, setError] = useState<string>()
  const groups = useQuery({
    queryKey: ['talent-pool-groups', { status: 'active', limit: 100 }],
    queryFn: () => fetchTalentPoolGroups({ status: 'active', limit: 100 }),
    enabled: open,
  })
  const addMutation = useMutation({
    mutationFn: (values: MembershipFormValues) => {
      const group = groups.data?.items.find((item) => item.id === values.groupId)
      if (!group) throw new Error('请选择有效的人才分组')
      return addTalentPoolMemberships(
        group.id,
        group.version,
        candidateIds,
        values.reason.trim(),
      )
    },
    onSuccess: (result) => {
      form.resetFields()
      setError(undefined)
      onSuccess(result)
    },
    onError: (reason) => {
      setError(reason instanceof ApiError ? reason.message : '加入人才库失败，请稍后重试')
    },
  })

  return (
    <Modal
      open={open}
      title={
        <span>
          <DatabaseOutlined /> 加入人才库
        </span>
      }
      okText="确认加入"
      cancelText="取消"
      confirmLoading={addMutation.isPending}
      okButtonProps={{ disabled: !groups.data?.items.length }}
      onOk={() => form.submit()}
      onCancel={() => {
        form.resetFields()
        setError(undefined)
        onClose()
      }}
      destroyOnHidden
    >
      <Text type="secondary">已选择 {candidateIds.length} 位候选人</Text>
      {error && <Alert className="talent-modal-alert" type="error" showIcon message={error} />}
      {groups.isError && (
        <Alert
          className="talent-modal-alert"
          type="error"
          showIcon
          message="人才分组读取失败"
        />
      )}
      {!groups.isPending && !groups.data?.items.length && (
        <Alert
          className="talent-modal-alert"
          type="info"
          showIcon
          message="请先在人才库中创建一个有效分组"
        />
      )}
      <Form<MembershipFormValues>
        form={form}
        layout="vertical"
        onFinish={(values) => addMutation.mutate(values)}
      >
        <Form.Item
          label="人才分组"
          name="groupId"
          rules={[{ required: true, message: '请选择人才分组' }]}
        >
          <Select
            aria-label="人才分组"
            loading={groups.isPending}
            placeholder="选择共享人才分组"
            options={(groups.data?.items ?? []).map((group) => ({
              value: group.id,
              label: `${group.name}（${group.member_count} 人）`,
            }))}
          />
        </Form.Item>
        <Form.Item
          label="入库原因"
          name="reason"
          rules={[{ required: true, whitespace: true, message: '请填写入库原因' }]}
        >
          <Input.TextArea
            aria-label="入库原因"
            rows={4}
            maxLength={2_000}
            showCount
            placeholder="说明候选人值得长期关注的原因"
          />
        </Form.Item>
      </Form>
    </Modal>
  )
}
